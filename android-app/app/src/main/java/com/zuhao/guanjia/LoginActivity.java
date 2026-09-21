package com.zuhao.guanjia;

import android.app.AlertDialog;
import android.content.DialogInterface;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashMap;
import java.util.Map;

public class LoginActivity extends AppCompatActivity {

    private static final String API_BASE = "http://43.129.201.203";

    private static final Map<String, String> PLATFORM_URLS = new HashMap<>();
    static {
        PLATFORM_URLS.put("uhaozu", "https://www.uhaozu.com/login");
        PLATFORM_URLS.put("mima", "https://www.mimaapp.com/");
        PLATFORM_URLS.put("xubei", "https://passport.xubei.com/");
    }

    private static final Map<String, String> PLATFORM_NAMES = new HashMap<>();
    static {
        PLATFORM_NAMES.put("uhaozu", "U号租");
        PLATFORM_NAMES.put("mima", "密马");
        PLATFORM_NAMES.put("xubei", "虚贝");
    }

    private WebView webView;
    private Button btnCancel;
    private Button btnComplete;
    private TextView tvTitle;
    private String platform;
    private String loginUrl;
    private String authToken = "";
    private boolean isSaving = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_login);

        platform = getIntent().getStringExtra("platform");
        loginUrl = PLATFORM_URLS.get(platform);
        authToken = getIntent().getStringExtra("auth_token") != null ? getIntent().getStringExtra("auth_token") : "";

        if (loginUrl == null) {
            Toast.makeText(this, "不支持的平台", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }

        webView = findViewById(R.id.webView);
        btnCancel = findViewById(R.id.btnCancel);
        btnComplete = findViewById(R.id.btnComplete);
        tvTitle = findViewById(R.id.tvTitle);

        tvTitle.setText(PLATFORM_NAMES.get(platform) + " 登录");

        setupWebView();
        webView.loadUrl(loginUrl);

        btnCancel.setOnClickListener(v -> finish());

        btnComplete.setOnClickListener(v -> {
            if (isSaving) return;
            confirmAndSave();
        });
    }

    private void setupWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        // 接受第三方Cookie（重要！）
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
            }

            @Override
            public void onPageFinished(WebView view, String url) {
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return false;
            }
        });

        webView.setWebChromeClient(new WebChromeClient());
    }

    private void confirmAndSave() {
        new AlertDialog.Builder(this)
            .setTitle("确认登录")
            .setMessage("确认已经在" + PLATFORM_NAMES.get(platform) + "登录成功了吗？确认后系统会自动保存登录凭证。")
            .setPositiveButton("确认登录", (dialog, which) -> saveCredentials())
            .setNegativeButton("再等等", null)
            .show();
    }

    private void saveCredentials() {
        isSaving = true;
        btnComplete.setEnabled(false);
        btnComplete.setText("保存中...");

        // WebView操作必须在UI线程执行！
        runOnUiThread(() -> {
            try {
                // 获取当前页面URL
                String currentUrl = webView.getUrl();
                if (currentUrl == null) currentUrl = loginUrl;

                // 获取Cookie
                CookieManager cookieManager = CookieManager.getInstance();
                String cookies = cookieManager.getCookie(currentUrl);
                if (cookies == null) cookies = "";

                final String finalCookies = cookies;
                final String finalCurrentUrl = currentUrl;

                // 从localStorage获取token（密马用），evaluateJavascript也必须在UI线程
                webView.evaluateJavascript(
                    "(function() { try { for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k.toLowerCase().indexOf('token')>=0||k.toLowerCase().indexOf('jwt')>=0)return localStorage.getItem(k);} } catch(e){} return ''; })()",
                    value -> {
                        String t = value.replace("\"", "").replace("\"", "");
                        if (!t.equals("null") && !t.isEmpty()) {
                            saveToApi(finalCookies, t, finalCurrentUrl);
                        } else {
                            saveToApi(finalCookies, "", finalCurrentUrl);
                        }
                    }
                );
            } catch (Exception e) {
                runOnUiThread(() -> {
                    isSaving = false;
                    btnComplete.setEnabled(true);
                    btnComplete.setText("登录完成");
                    Toast.makeText(LoginActivity.this, "保存失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void saveToApi(String cookies, String token, String currentUrl) {
        new Thread(() -> {
            try {
                URL url = new URL(API_BASE + "/api/browser/native-login");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                if (authToken != null && !authToken.isEmpty()) {
                    conn.setRequestProperty("Authorization", "Bearer " + authToken);
                }
                conn.setDoOutput(true);
                conn.setConnectTimeout(30000);
                conn.setReadTimeout(30000);

                JSONObject json = new JSONObject();
                json.put("platform", platform);
                json.put("cookies", cookies);
                json.put("token", token);
                json.put("current_url", currentUrl);
                json.put("nickname", PLATFORM_NAMES.get(platform) + "账号");

                try (OutputStream os = conn.getOutputStream()) {
                    os.write(json.toString().getBytes("UTF-8"));
                }

                int responseCode = conn.getResponseCode();
                BufferedReader reader;
                if (responseCode == 200) {
                    reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                } else {
                    reader = new BufferedReader(new InputStreamReader(conn.getErrorStream()));
                }
                StringBuilder response = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    response.append(line);
                }
                reader.close();

                JSONObject result = new JSONObject(response.toString());

                runOnUiThread(() -> {
                    isSaving = false;
                    if (responseCode == 200 && result.optBoolean("success", false)) {
                        Toast.makeText(LoginActivity.this, "登录成功！正在同步数据...", Toast.LENGTH_SHORT).show();
                        setResult(RESULT_OK);
                        finish();
                    } else {
                        btnComplete.setEnabled(true);
                        btnComplete.setText("登录完成");
                        Toast.makeText(LoginActivity.this, "保存失败: " + result.optString("detail", "未知错误"), Toast.LENGTH_LONG).show();
                    }
                });

            } catch (Exception e) {
                runOnUiThread(() -> {
                    isSaving = false;
                    btnComplete.setEnabled(true);
                    btnComplete.setText("登录完成");
                    Toast.makeText(LoginActivity.this, "网络错误: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        }).start();
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
