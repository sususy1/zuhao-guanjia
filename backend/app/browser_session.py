"""
远程浏览器会话管理
用于用户自己在网页上登录平台，服务器只负责采集数据
"""
import asyncio
import base64
import threading
import logging
from typing import Dict, Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# 会话存储
_sessions: Dict[str, dict] = {}
_sessions_lock = threading.Lock()


class BrowserSession:
    """浏览器会话"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.initialized = False

    def _run_loop(self):
        """在独立线程中运行事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _init_browser(self, url: str):
        """初始化浏览器并打开页面"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--window-size=1280,900',
            ]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # 移除webdriver标志
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        """)
        self.page = await self.context.new_page()
        await self.page.goto(url, wait_until="commit", timeout=60000)
        await self.page.wait_for_timeout(3000)
        self.initialized = True
        logger.info(f"浏览器会话 {self.session_id} 初始化完成，URL: {url}")

    def start(self, url: str):
        """启动浏览器会话（同步入口）"""
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        # 等待事件循环启动
        while self.loop is None:
            pass
        # 在事件循环中执行初始化
        future = asyncio.run_coroutine_threadsafe(self._init_browser(url), self.loop)
        future.result(timeout=90)  # 最多等待90秒

    def _ensure_loop(self):
        """确保事件循环存在"""
        if self.loop is None:
            raise Exception("浏览器会话未启动")

    def screenshot(self) -> str:
        """截图，返回base64编码的PNG图片"""
        self._ensure_loop()
        async def _shot():
            return await self.page.screenshot(type="png", full_page=False)
        future = asyncio.run_coroutine_threadsafe(_shot(), self.loop)
        img_bytes = future.result(timeout=30)
        return base64.b64encode(img_bytes).decode("utf-8")

    def click(self, x: float, y: float):
        """点击指定坐标（坐标为相对于视口的像素坐标）"""
        self._ensure_loop()
        async def _click():
            await self.page.mouse.click(x, y)
            await self.page.wait_for_timeout(1000)
        future = asyncio.run_coroutine_threadsafe(_click(), self.loop)
        future.result(timeout=30)

    def type(self, text: str):
        """在当前焦点元素输入文字"""
        self._ensure_loop()
        async def _type():
            await self.page.keyboard.type(text, delay=50)
            await self.page.wait_for_timeout(500)
        future = asyncio.run_coroutine_threadsafe(_type(), self.loop)
        future.result(timeout=30)

    def press_key(self, key: str):
        """按键"""
        self._ensure_loop()
        async def _press():
            await self.page.keyboard.press(key)
            await self.page.wait_for_timeout(500)
        future = asyncio.run_coroutine_threadsafe(_press(), self.loop)
        future.result(timeout=30)

    def get_cookies(self) -> Dict[str, str]:
        """获取当前页面的所有Cookie"""
        self._ensure_loop()
        async def _cookies():
            cookies = await self.context.cookies()
            return {c["name"]: c["value"] for c in cookies}
        future = asyncio.run_coroutine_threadsafe(_cookies(), self.loop)
        return future.result(timeout=15)

    def get_url(self) -> str:
        """获取当前页面URL"""
        self._ensure_loop()
        async def _url():
            return self.page.url
        future = asyncio.run_coroutine_threadsafe(_url(), self.loop)
        return future.result(timeout=10)

    def evaluate(self, script: str):
        """在页面中执行JS"""
        self._ensure_loop()
        async def _eval():
            return await self.page.evaluate(script)
        future = asyncio.run_coroutine_threadsafe(_eval(), self.loop)
        return future.result(timeout=15)

    def close(self):
        """关闭浏览器会话"""
        if self.loop and self.browser:
            async def _close():
                try:
                    await self.browser.close()
                    await self.playwright.stop()
                except:
                    pass
            try:
                future = asyncio.run_coroutine_threadsafe(_close(), self.loop)
                future.result(timeout=10)
            except:
                pass
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        logger.info(f"浏览器会话 {self.session_id} 已关闭")


# 平台登录页URL映射
PLATFORM_LOGIN_URLS = {
    "uhaozu": "https://www.uhaozu.com/login",
    "mima": "https://www.mimaapp.com/",
    "xubei": "https://passport.xubei.com/",
    "xubei_user": "https://user.xubei.com/login",
}


def create_session(platform: str) -> Tuple[str, str]:
    """创建浏览器会话，返回(session_id, screenshot_base64)"""
    import uuid
    session_id = str(uuid.uuid4())[:8]

    # 获取登录页URL
    url = PLATFORM_LOGIN_URLS.get(platform)
    if not url:
        raise Exception(f"不支持的平台: {platform}")

    session = BrowserSession(session_id)
    try:
        session.start(url)
    except Exception as e:
        session.close()
        raise Exception(f"打开登录页失败: {e}")

    with _sessions_lock:
        _sessions[session_id] = {
            "session": session,
            "platform": platform,
            "created_at": __import__("time").time(),
        }

    screenshot = session.screenshot()
    return session_id, screenshot


def get_session(session_id: str) -> Optional[BrowserSession]:
    """获取浏览器会话"""
    with _sessions_lock:
        data = _sessions.get(session_id)
        if data:
            return data["session"]
    return None


def close_session(session_id: str):
    """关闭浏览器会话"""
    with _sessions_lock:
        data = _sessions.pop(session_id, None)
    if data:
        data["session"].close()


def cleanup_expired_sessions(max_age: int = 600):
    """清理过期的会话（默认10分钟）"""
    import time
    now = time.time()
    expired = []
    with _sessions_lock:
        for sid, data in _sessions.items():
            if now - data["created_at"] > max_age:
                expired.append(sid)
    for sid in expired:
        close_session(sid)
    if expired:
        logger.info(f"清理了 {len(expired)} 个过期浏览器会话")
