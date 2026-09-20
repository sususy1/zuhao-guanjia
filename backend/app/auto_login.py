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
from typing import Dict, Optional, Tuple

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
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
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

        await page.wait_for_timeout(5000)

        # 检查登录结果 - 访问用户中心验证会话是否真正建立
        report("验证登录状态...")
        verify_success = False
        for retry in range(3):
            try:
                await page.goto("https://www.uhaozu.com/usercenter", wait_until="commit", timeout=60000)
                await page.wait_for_timeout(5000)
                verify_success = True
                break
            except Exception as e:
                report(f"第{retry+1}次验证登录失败: {e}，重试...")
                await page.wait_for_timeout(3000)
        if not verify_success:
            report("无法访问用户中心，但继续获取Cookie...")

        current_url = page.url
        page_text = ""
        try:
            page_text = await page.inner_text("body")
        except:
            pass

        # 判断是否真正登录成功：URL不含login，且页面包含用户中心相关文字
        is_logged_in = ("login" not in current_url.lower()) and (
            "退出" in page_text or "用户中心" in page_text or "我的" in page_text or "账号" in page_text
        )

        if not is_logged_in:
            report(f"登录验证失败，当前URL: {current_url}")
            report(f"页面内容前200字: {page_text[:200]}")
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


# 平台自动登录注册表
AUTO_LOGIN_FUNCTIONS = {
    "uhaozu": uhaozu_auto_login,
}


def supports_auto_login(platform: str) -> bool:
    """检查平台是否支持自动登录"""
    return platform in AUTO_LOGIN_FUNCTIONS


def do_auto_login(platform: str, username: str, password: str, progress_callback=None) -> Dict[str, str]:
    """执行平台自动登录，返回Cookie字典"""
    if platform not in AUTO_LOGIN_FUNCTIONS:
        raise Exception(f"平台 {platform} 不支持自动登录")
    return AUTO_LOGIN_FUNCTIONS[platform](username, password, progress_callback)
