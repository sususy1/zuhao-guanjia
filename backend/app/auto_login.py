"""
平台自动登录核心模块
使用Playwright + 超级鹰打码平台，自动完成各平台登录并获取Cookie
"""
import asyncio
import os
import base64
import json
import hashlib
import urllib.request
import urllib.parse
import logging
from typing import Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# 超级鹰配置
CJY_USER = os.environ.get("CJY_USER", "20260920zqn2p7lm")
CJY_PASS = os.environ.get("CJY_PASS", "Zhang0510.")
CJY_SOFT_ID = os.environ.get("CJY_SOFT_ID", "983881")
CJY_PASS_MD5 = hashlib.md5(CJY_PASS.encode("utf-8")).hexdigest()


def cjy_recognize_text(img_bytes: bytes) -> Tuple[Dict[str, Tuple[int, int]], str]:
    """用超级鹰9800识别图片上所有文字的坐标
    Returns: (文字坐标字典, pic_id)
    """
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
    url = "https://upload.chaojiying.net/Upload/Processing.php"
    data = urllib.parse.urlencode({
        "user": CJY_USER,
        "pass2": CJY_PASS_MD5,
        "softid": CJY_SOFT_ID,
        "codetype": "9800",
        "len_min": "0",
        "file_base64": img_base64,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if result.get("err_no") != 0:
        raise Exception(f"超级鹰识别失败: {result.get('err_str')}")

    text_positions = {}
    for item in result["pic_str"].split("|"):
        parts = item.split(",")
        if len(parts) >= 3:
            char = parts[0]
            x = int(parts[1])
            y = int(parts[2])
            text_positions[char] = (x, y)

    return text_positions, result.get("pic_id", "")


async def _uhaozu_login_async(username: str, password: str, progress_callback=None) -> Dict[str, str]:
    """U号租异步自动登录，返回Cookie字典"""
    from playwright.async_api import async_playwright

    def report(msg):
        logger.info(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except:
                pass

    async with async_playwright() as p:
        report("启动浏览器...")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        # 反检测：移除webdriver标志
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            window.chrome = {runtime: {}};
        """)
        page = await context.new_page()

        report("打开登录页...")
        # 重试机制：香港服务器访问国内网站可能不稳定
        login_success = False
        for retry in range(3):
            try:
                await page.goto("https://www.uhaozu.com/user/login", wait_until="commit", timeout=60000)
                await page.wait_for_timeout(5000)
                login_success = True
                break
            except Exception as e:
                report(f"第{retry+1}次打开登录页失败: {e}，重试...")
                await page.wait_for_timeout(3000)
        if not login_success:
            await browser.close()
            raise Exception("无法打开U号租登录页（网络超时）")

        report("切换到账号登录...")
        tabs = await page.query_selector_all(".login-top span")
        for tab in tabs:
            text = await tab.inner_text()
            if "账号" in text:
                await tab.click()
                break
        await page.wait_for_timeout(1500)

        report("输入账号密码...")
        all_inputs = await page.query_selector_all("input")
        for inp in all_inputs:
            if await inp.is_visible():
                name = await inp.get_attribute("name") or ""
                typ = await inp.get_attribute("type") or ""
                if name == "userName":
                    await inp.fill(username)
                elif typ == "password":
                    await inp.fill(password)

        report("勾选同意协议...")
        checkboxes = await page.query_selector_all("input[type='checkbox']")
        for cb in checkboxes:
            if await cb.is_visible():
                await cb.check()
        await page.wait_for_timeout(1000)

        report("点击登录...")
        login_btn = await page.query_selector(".login-btn-a")
        if not login_btn:
            login_btn = await page.query_selector(".login-btn")
        await login_btn.click()
        await page.wait_for_timeout(3000)

        # 检查验证弹窗
        captcha_frame = None
        for frame in page.frames:
            if "captcha" in frame.url.lower() or "turing" in frame.url.lower():
                captcha_frame = frame
                break

        if captcha_frame:
            report("检测到验证码，开始自动识别...")

            for retry in range(3):
                report(f"第 {retry+1} 次验证尝试...")
                await captcha_frame.wait_for_timeout(2000)

                # 获取提示文字
                tip_text = ""
                all_text = await page.inner_text("body")
                if "请依次点击" in all_text:
                    idx = all_text.index("请依次点击")
                    remaining = all_text[idx+6:idx+30]
                    tip_text = remaining.split("\n")[0].strip()
                    tip_text = tip_text.replace("：", "").replace(":", "").strip()

                if not tip_text:
                    frame_text = await captcha_frame.inner_text("body")
                    if "请依次点击" in frame_text:
                        idx = frame_text.index("请依次点击")
                        remaining = frame_text[idx+6:idx+30]
                        tip_text = remaining.split("\n")[0].strip()
                        tip_text = tip_text.replace("：", "").replace(":", "").strip()

                target_chars = [c for c in tip_text if '\u4e00' <= c <= '\u9fff']
                report(f"提示文字: {tip_text} -> 需要点击: {target_chars}")

                if not target_chars:
                    report("未提取到提示文字，刷新验证...")
                    refresh_btn = await page.query_selector(".tc-refresh, [class*='refresh']")
                    if refresh_btn:
                        await refresh_btn.click()
                    await page.wait_for_timeout(2000)
                    continue

                # 获取验证图片位置
                img_x, img_y, img_w, img_h = 445, 290, 310, 265
                try:
                    imgs = await captcha_frame.query_selector_all("img")
                    for img in imgs:
                        box = await img.bounding_box()
                        if box and box["width"] > 200 and box["height"] > 100:
                            img_x = int(box["x"])
                            img_y = int(box["y"])
                            img_w = int(box["width"])
                            img_h = int(box["height"])
                            break
                except:
                    pass

                # 裁剪验证图片
                captcha_bytes = await page.screenshot(clip={
                    "x": img_x, "y": img_y, "width": img_w, "height": img_h
                })

                # 超级鹰识别
                report("超级鹰识别文字坐标...")
                try:
                    text_positions, pic_id = cjy_recognize_text(captcha_bytes)
                    report(f"识别结果: {text_positions}")
                except Exception as e:
                    report(f"识别失败: {e}，刷新重试...")
                    refresh_btn = await page.query_selector(".tc-refresh, [class*='refresh']")
                    if refresh_btn:
                        await refresh_btn.click()
                    await page.wait_for_timeout(2000)
                    continue

                # 按顺序点击
                report(f"按顺序点击 {len(target_chars)} 个字...")
                for char in target_chars:
                    if char in text_positions:
                        rel_x, rel_y = text_positions[char]
                        abs_x = img_x + rel_x
                        abs_y = img_y + rel_y
                        await page.mouse.click(abs_x, abs_y)
                        await page.wait_for_timeout(800)

                # 点击确定按钮（JS触发，不移动鼠标）
                report("点击确定按钮...")
                try:
                    await captcha_frame.evaluate("""() => {
                        const buttons = document.querySelectorAll('button');
                        for (const btn of buttons) {
                            if (btn.innerText && btn.innerText.trim() === '确定' && btn.offsetParent !== null) {
                                btn.click();
                                return 'clicked';
                            }
                        }
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.children.length > 0) continue;
                            if (el.innerText && el.innerText.trim() === '确定' && el.offsetParent !== null) {
                                el.click();
                                return 'clicked';
                            }
                        }
                        return 'not found';
                    }""")
                except:
                    pass

                await page.wait_for_timeout(3000)

                # 检查验证是否通过
                captcha_still_exists = any(
                    "captcha" in f.url.lower() or "turing" in f.url.lower()
                    for f in page.frames
                )

                if not captcha_still_exists:
                    report("✅ 验证通过！")
                    break
                else:
                    report("验证未通过，刷新重试...")
                    try:
                        refresh_btns = await captcha_frame.query_selector_all("[class*='refresh'], [class*='reload']")
                        for rb in refresh_btns:
                            if await rb.is_visible():
                                await rb.click()
                                break
                    except:
                        pass
                    await page.wait_for_timeout(2000)

        await page.wait_for_timeout(8000)

        # 检查登录结果 - 在浏览器内直接调用商品API测试（比访问页面更可靠）
        report("验证登录状态（调用商品API）...")
        api_test_result = None
        try:
            api_test_result = await page.evaluate("""async () => {
                try {
                    const resp = await fetch('https://www.uhaozu.com/goods/usercenter/list', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({page: 1, pageSize: 5})
                    });
                    const text = await resp.text();
                    return {status: resp.status, text: text.substring(0, 300)};
                } catch(e) {
                    return {error: e.message};
                }
            }""")
            report(f"API测试结果: {api_test_result}")
        except Exception as e:
            report(f"API测试异常: {e}")

        # 判断登录是否成功：API返回JSON且包含商品数据或不包含loginUrl
        is_logged_in = False
        if api_test_result and 'text' in api_test_result:
            text = api_test_result['text']
            if '"loginUrl"' not in text and 'responseCode' not in text:
                is_logged_in = True
            elif '"data"' in text or '"list"' in text or '"total"' in text:
                is_logged_in = True
            elif 'responseCode":"0"' in text or 'responseCode":0' in text:
                is_logged_in = True

        # 额外检查：当前URL是否已离开登录页
        current_url = page.url
        if 'login' not in current_url.lower():
            is_logged_in = True

        if not is_logged_in:
            report(f"登录验证失败，当前URL: {current_url}")
            report(f"API返回: {api_test_result}")
            await browser.close()
            raise Exception("登录失败，会话未建立（可能被风控拦截）")

        report("登录验证通过，获取Cookie...")
        cookies = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        await browser.close()
        return cookie_dict


def uhaozu_auto_login(username: str, password: str, progress_callback=None) -> Dict[str, str]:
    """U号租自动登录（同步入口），返回Cookie字典"""
    return asyncio.run(_uhaozu_login_async(username, password, progress_callback))


def cjy_recognize_captcha(img_bytes: bytes, codetype: str = "1004") -> Tuple[str, str]:
    """用超级鹰识别普通英文数字验证码
    Args:
        img_bytes: 验证码图片字节
        codetype: 验证码类型，1004=1-4位英文数字, 1005=1-5位, 1006=1-6位
    Returns: (识别结果, pic_id)
    """
    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
    url = "https://upload.chaojiying.net/Upload/Processing.php"
    data = urllib.parse.urlencode({
        "user": CJY_USER,
        "pass2": CJY_PASS_MD5,
        "softid": CJY_SOFT_ID,
        "codetype": codetype,
        "len_min": "0",
        "file_base64": img_base64,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if result.get("err_no") != 0:
        raise Exception(f"超级鹰识别失败: {result.get('err_str')}")

    return result.get("pic_str", ""), result.get("pic_id", "")


def xubei_auto_login(username: str, password: str, progress_callback=None) -> Dict[str, str]:
    """虚贝自动登录（Playwright浏览器方式，账号密码+图形验证码），返回Cookie字典"""
    return asyncio.run(_xubei_login_async(username, password, progress_callback))


async def _xubei_login_async(username: str, password: str, progress_callback=None) -> Dict[str, str]:
    """虚贝异步自动登录（Playwright浏览器方式）"""
    from playwright.async_api import async_playwright

    def report(msg):
        logger.info(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except:
                pass

    async with async_playwright() as p:
        report("启动浏览器...")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # 移除webdriver标志
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        """)

        page = await context.new_page()

        max_retries = 5
        for attempt in range(max_retries):
            try:
                report(f"打开虚贝登录页（第{attempt+1}次）...")
                await page.goto("https://passport.xubei.com/", wait_until="commit", timeout=60000)
                await page.wait_for_timeout(3000)

                # 切换到账号密码登录
                report("切换到账号密码登录...")
                try:
                    pwd_login = await page.query_selector("text=账号密码登录")
                    if pwd_login:
                        await pwd_login.click()
                        await page.wait_for_timeout(2000)
                except:
                    pass

                # 输入手机号
                report("输入账号密码...")
                phone_input = await page.query_selector("input.phone")
                if phone_input:
                    await phone_input.fill(username)

                # 输入密码
                pwd_input = await page.query_selector("input.pwd")
                if pwd_input:
                    await pwd_input.fill(password)

                # 获取验证码图片
                report("获取验证码图片...")
                captcha_bytes = None

                # 方式1：查找验证码图片元素
                vcode_img = None
                for selector in ["img.vcodeImg", ".vcodeImg img", "img[src*='vcode']", ".changeVcode img", "img[alt*='验证码']"]:
                    try:
                        vcode_img = await page.query_selector(selector)
                        if vcode_img:
                            report(f"找到验证码图片: {selector}")
                            break
                    except:
                        pass

                if vcode_img:
                    try:
                        captcha_bytes = await vcode_img.screenshot()
                    except:
                        pass

                # 方式2：通过验证码输入框旁边的位置估算
                if not captcha_bytes or len(captcha_bytes) < 100:
                    vcode_input = await page.query_selector("input.vcode")
                    if vcode_input:
                        box = await vcode_input.bounding_box()
                        if box:
                            # 验证码图片通常在输入框右边，宽度约100-120px
                            try:
                                captcha_bytes = await page.screenshot(clip={
                                    "x": box["x"] + box["width"] + 5,
                                    "y": box["y"] - 2,
                                    "width": 130,
                                    "height": box["height"] + 4
                                })
                                report("通过输入框位置截取验证码")
                            except:
                                pass

                # 方式3：查找所有图片，找尺寸合适的
                if not captcha_bytes or len(captcha_bytes) < 100:
                    images = await page.query_selector_all("img")
                    for img in images:
                        try:
                            box = await img.bounding_box()
                            if box and 80 < box["width"] < 150 and 30 < box["height"] < 60:
                                src = await img.get_attribute("src") or ""
                                if "vcode" in src or "captcha" in src or "verify" in src or not src.startswith("data:"):
                                    captcha_bytes = await img.screenshot()
                                    report(f"通过尺寸找到验证码图片: {box['width']}x{box['height']}")
                                    break
                        except:
                            pass

                if not captcha_bytes or len(captcha_bytes) < 100:
                    report("无法获取验证码图片，重试...")
                    await page.wait_for_timeout(2000)
                    continue

                # 超级鹰识别验证码
                report("超级鹰识别验证码...")
                try:
                    vcode, pic_id = cjy_recognize_captcha(captcha_bytes, codetype="1004")
                    report(f"识别结果: {vcode}")
                except Exception as e:
                    report(f"识别失败: {e}，刷新重试...")
                    try:
                        refresh_btn = await page.query_selector(".changeVcode")
                        if refresh_btn:
                            await refresh_btn.click()
                    except:
                        pass
                    await page.wait_for_timeout(2000)
                    continue

                if not vcode or len(vcode) < 3:
                    report("验证码识别结果太短，刷新重试...")
                    try:
                        refresh_btn = await page.query_selector(".changeVcode")
                        if refresh_btn:
                            await refresh_btn.click()
                    except:
                        pass
                    await page.wait_for_timeout(2000)
                    continue

                # 输入验证码
                report("输入验证码...")
                vcode_input = await page.query_selector("input.vcode")
                if vcode_input:
                    await vcode_input.fill(vcode)

                # 点击登录按钮（用JS触发，避免被遮挡）
                report("点击登录...")
                try:
                    await page.evaluate("""() => {
                        // 尝试多种方式找到并点击登录按钮
                        const btn = document.querySelector('.login-btn') || 
                                    document.querySelector('#login-btn') ||
                                    document.querySelector('input[value="立即登录"]') ||
                                    document.querySelector('button[type="submit"]');
                        if (btn) {
                            btn.click();
                            return 'clicked: ' + btn.tagName + '.' + btn.className;
                        }
                        // 尝试触发表单提交
                        const form = document.querySelector('form');
                        if (form) {
                            form.submit();
                            return 'form submitted';
                        }
                        return 'button not found';
                    }""")
                except Exception as e:
                    report(f"JS点击异常: {e}，尝试普通点击...")
                    try:
                        login_btn = await page.query_selector(".login-btn, #login-btn, input[value='立即登录']")
                        if login_btn:
                            await login_btn.click(timeout=10000)
                    except:
                        pass

                await page.wait_for_timeout(8000)

                # 检查登录结果
                current_url = page.url
                report(f"当前URL: {current_url}")

                # 检查是否有错误提示
                error_msg = ""
                try:
                    err_el = await page.query_selector(".err-info, .error, .message")
                    if err_el:
                        error_msg = await err_el.inner_text()
                        if error_msg and len(error_msg) > 2:
                            report(f"错误提示: {error_msg}")
                except:
                    pass

                # 判断是否登录成功：URL变化或错误提示为空
                is_logged_in = False
                if 'passport.xubei.com' not in current_url and 'login' not in current_url.lower():
                    is_logged_in = True
                elif error_msg and ('密码' in error_msg or '账号' in error_msg or '冻结' in error_msg or '限制' in error_msg):
                    raise Exception(f"登录失败: {error_msg}")
                elif not error_msg or '验证码' not in error_msg:
                    # 可能登录成功但还在跳转
                    await page.wait_for_timeout(3000)
                    current_url = page.url
                    if 'passport.xubei.com' not in current_url:
                        is_logged_in = True

                if is_logged_in:
                    report("✅ 登录成功！获取Cookie...")
                    cookies = await context.cookies()
                    cookie_dict = {c["name"]: c["value"] for c in cookies}

                    # 确保关键Cookie存在
                    if 'xubei_token' not in cookie_dict:
                        # 尝试从localStorage获取
                        try:
                            local_data = await page.evaluate("() => JSON.stringify(window.localStorage)")
                            import json as _json
                            local_dict = _json.loads(local_data)
                            for key, value in local_dict.items():
                                if 'token' in key.lower() or 'auth' in key.lower():
                                    cookie_dict[key] = str(value)
                        except:
                            pass

                    await browser.close()
                    return cookie_dict
                else:
                    report(f"登录未成功，刷新重试...")
                    await page.reload(wait_until="commit", timeout=60000)
                    await page.wait_for_timeout(2000)
                    continue

            except Exception as e:
                if "密码" in str(e) or "账号" in str(e) or "冻结" in str(e) or "限制" in str(e):
                    await browser.close()
                    raise
                report(f"登录异常: {e}，重试...")
                try:
                    await page.reload(wait_until="commit", timeout=60000)
                except:
                    pass
                await page.wait_for_timeout(3000)
                continue

        await browser.close()
        raise Exception(f"虚贝登录失败，已重试{max_retries}次")


def mima_login_with_code(phone: str, code: str, progress_callback=None) -> Dict[str, str]:
    """密马半自动登录（手机号+短信验证码），返回Token字典"""
    import requests

    def report(msg):
        logger.info(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except:
                pass

    report("调用密马登录API...")

    headers = {
        "device": "2",
        "fp": "",
        "Referer": "https://www.mimaapp.com/",
        "Origin": "https://www.mimaapp.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
    }

    # 调用登录API
    resp = requests.post(
        "https://api.mimaapp.cn/v1/user/login",
        headers=headers,
        json={"phone": phone, "code": code},
        timeout=15
    )
    result = resp.json()

    if result.get("code") != 0:
        raise Exception(f"密马登录失败: {result.get('msg', '未知错误')}")

    # 获取Token
    data = result.get("data", {})
    token = data.get("token") or data.get("access_token") or data.get("jwt") or ""

    if not token:
        # 尝试从其他字段获取
        for key in ["token", "access_token", "jwt", "authorization", "auth_token"]:
            if key in data:
                token = str(data[key])
                break

    if not token:
        raise Exception(f"密马登录成功但未获取到Token，返回数据: {json.dumps(data, ensure_ascii=False)[:200]}")

    report("✅ 登录成功，获取到Token")

    # 返回Token字典（统一用token_data字段）
    return {"token": token}


def mima_send_sms(phone: str) -> Dict[str, Any]:
    """发送密马短信验证码（可能因fp问题失败，失败时提示用户在App上获取）"""
    import requests

    headers = {
        "device": "2",
        "fp": "",
        "Referer": "https://www.mimaapp.com/",
        "Origin": "https://www.mimaapp.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            "https://api.mimaapp.cn/v1/common/send_sms",
            headers=headers,
            json={"phone": phone},
            timeout=15
        )
        result = resp.json()
        if result.get("code") == 0:
            return {"success": True, "message": "验证码已发送"}
        else:
            return {"success": False, "message": result.get("msg", "发送失败，请在密马App上获取验证码")}
    except Exception as e:
        return {"success": False, "message": f"发送失败: {e}，请在密马App上获取验证码"}


# 平台自动登录注册表
AUTO_LOGIN_FUNCTIONS = {
    "uhaozu": uhaozu_auto_login,
    "xubei": xubei_auto_login,
}

# 支持半自动登录的平台（需要用户输入验证码）
SEMI_AUTO_LOGIN_PLATFORMS = {
    "mima": mima_login_with_code,
}


def supports_auto_login(platform: str) -> bool:
    """检查平台是否支持自动登录"""
    return platform in AUTO_LOGIN_FUNCTIONS


def do_auto_login(platform: str, username: str, password: str, progress_callback=None) -> Dict[str, str]:
    """执行平台自动登录，返回Cookie字典"""
    if platform not in AUTO_LOGIN_FUNCTIONS:
        raise Exception(f"平台 {platform} 不支持自动登录")
    return AUTO_LOGIN_FUNCTIONS[platform](username, password, progress_callback)
