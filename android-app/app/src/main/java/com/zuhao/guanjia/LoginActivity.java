package com.zuhao.guanjia;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

public class LoginActivity extends Activity {
    private WebView webView;
    private Button btnComplete, btnRefresh;
    private ProgressBar progressBar;
    private TextView tvStatus;
    private String platform;
    private String loginUrl;
    private String API_BASE;
    private String authToken;
    private boolean isSaving = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_login);

        platform = getIntent().getStringExtra("platform");
        loginUrl = getIntent().getStringExtra("login_url");
        API_BASE = getIntent().getStringExtra("api_base");
        authToken = getIntent().getStringExtra("token");

        webView = findViewById(R.id.webView);
        btnComplete = findViewById(R.id.btnComplete);
        btnRefresh = findViewById(R.id.btnRefresh);
        progressBar = findViewById(R.id.progressBar);
        tvStatus = findViewById(R.id.tvStatus);

        initWebView();
        loadLoginUrl();

        btnComplete.setOnClickListener(v -> syncFromWebView());
        btnRefresh.setOnClickListener(v -> webView.reload());
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void initWebView() {
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setAllowContentAccess(true);
        webView.getSettings().setLoadWithOverviewMode(true);
        webView.getSettings().setUseWideViewPort(true);
        webView.getSettings().setBuiltInZoomControls(true);
        webView.getSettings().setDisplayZoomControls(false);

        // 加JS接口，用来接收WebView传来的数据
        webView.addJavascriptInterface(new JsInterface(), "AndroidBridge");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                progressBar.setVisibility(View.GONE);
                tvStatus.setText("登录页已加载，请登录后点\"完成同步\"");
            }
        });
    }

    private void loadLoginUrl() {
        progressBar.setVisibility(View.VISIBLE);
        webView.loadUrl(loginUrl);
    }

    // JS接口，WebView里的JS可以调用这个方法把数据传回来
    public class JsInterface {
        @JavascriptInterface
        public void onDataReady(String jsonData) {
            Log.d("LoginActivity", "收到WebView传来的数据，长度: " + jsonData.length());
            runOnUiThread(() -> {
                tvStatus.setText("正在上传数据到服务器...");
            });
            // 把数据上传到服务器
            new Thread(() -> {
                try {
                    uploadDataToServer(jsonData);
                } catch (Exception e) {
                    runOnUiThread(() -> {
                        Toast.makeText(LoginActivity.this, "上传失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                        tvStatus.setText("同步失败，请重试");
                        isSaving = false;
                        btnComplete.setEnabled(true);
                        btnComplete.setText("完成同步");
                    });
                }
            }).start();
        }

        @JavascriptInterface
        public void onSyncError(String message) {
            runOnUiThread(() -> {
                Toast.makeText(LoginActivity.this, "同步失败: " + message, Toast.LENGTH_LONG).show();
                tvStatus.setText("同步失败，请重试");
                isSaving = false;
                btnComplete.setEnabled(true);
                btnComplete.setText("完成同步");
            });
        }
    }

    private void syncFromWebView() {
        if (isSaving) return;
        isSaving = true;
        btnComplete.setEnabled(false);
        btnComplete.setText("同步中...");
        tvStatus.setText("正在获取商品数据...");

        // 根据不同平台，注入不同的JS代码
        String jsCode = "";
        if ("uhaozu".equals(platform)) {
            // U号租：调用商品列表API
            jsCode = "(function() {" +
                "fetch('/goods/usercenter/list', {" +
                "  method: 'POST'," +
                "  headers: {'Content-Type': 'application/json;charset=utf-8'}," +
                "  body: JSON.stringify({page:1, pageSize:200, isViewAuthStatus:true})," +
                "  credentials: 'include'" +
                "})" +
                ".then(r => r.json())" +
                ".then(data => {" +
                "  AndroidBridge.onDataReady(JSON.stringify(data));" +
                "})" +
                ".catch(e => AndroidBridge.onSyncError(e.message));" +
                "})();";
        } else if ("mima".equals(platform)) {
            // 密马：先试试这个接口
            jsCode = "(function() {" +
                "fetch('/api/goods/list?page=1&pageSize=200', {" +
                "  credentials: 'include'" +
                "})" +
                ".then(r => r.json())" +
                ".then(data => {" +
                "  AndroidBridge.onDataReady(JSON.stringify(data));" +
                "})" +
                ".catch(e => AndroidBridge.onSyncError(e.message));" +
                "})();";
        } else if ("xubei".equals(platform)) {
            // 虚贝
            jsCode = "(function() {" +
                "fetch('/user/goods/list?page=1&pageSize=200', {" +
                "  credentials: 'include'" +
                "})" +
                ".then(r => r.json())" +
                ".then(data => {" +
                "  AndroidBridge.onDataReady(JSON.stringify(data));" +
                "})" +
                ".catch(e => AndroidBridge.onSyncError(e.message));" +
                "})();";
        }

        webView.evaluateJavascript(jsCode, null);
    }

    private void uploadDataToServer(String jsonData) throws Exception {
        URL url = new URL(API_BASE + "/api/import-listings");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setDoOutput(true);
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(30000);

        JSONObject payload = new JSONObject();
        payload.put("platform", platform);
        payload.put("data", new JSONObject(jsonData));

        OutputStream os = conn.getOutputStream();
        os.write(payload.toString().getBytes("UTF-8"));
        os.flush();
        os.close();

        int code = conn.getResponseCode();
        if (code == 200) {
            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            reader.close();
            Log.d("LoginActivity", "服务器返回: " + sb.toString());

            runOnUiThread(() -> {
                Toast.makeText(LoginActivity.this, "同步成功！", Toast.LENGTH_LONG).show();
                tvStatus.setText("同步成功！返回App查看");
                isSaving = false;
                // 延迟2秒关闭
                new Handler(Looper.getMainLooper()).postDelayed(() -> {
                    finish();
                }, 2000);
            });
        } else {
            throw new Exception("服务器返回错误码: " + code);
        }
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
        super.onDestroy();
        webView.destroy();
    }
}
