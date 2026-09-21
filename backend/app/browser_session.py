"""
远程浏览器会话管理（优化版）
- 全局锁：同时只能运行一个浏览器会话
- 优化Chromium参数：减少内存和线程占用
- 确保进程正确清理，避免残留
"""
import asyncio
import base64
import threading
import logging
import time
from typing import Dict, Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# 会话存储
_sessions: Dict[str, dict] = {}
_sessions_lock = threading.Lock()
# 全局浏览器锁：同时只能有一个浏览器会话
_browser_lock = threading.Lock()
# 当前活动会话ID
_active_session_id: Optional[str] = None


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
        self._closed = False

    def _run_loop(self):
        """在独立线程中运行事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _init_browser(self, url: str):
        """初始化浏览器并打开页面"""
        logger.info(f"[{self.session_id}] 启动Playwright...")
        self.playwright = await async_playwright().start()
        
        logger.info(f"[{self.session_id}] 启动Chromium（优化参数）...")
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-sync',
                '--disable-translate',
                '--disable-features=TranslateUI,site-per-process',
                '--mute-audio',
                '--no-first-run',
                '--no-default-browser-check',
                '--window-size=1024,768',
                '--single-process',  # 单进程模式，大幅减少线程数
            ]
        )
        logger.info(f"[{self.session_id}] Chromium启动成功")

        self.context = await self.browser.new_context(
            viewport={"width": 1024, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        """)
        self.page = await self.context.new_page()
        
        logger.info(f"[{self.session_id}] 正在打开页面: {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await self.page.wait_for_timeout(1500)
        self.initialized = True
        logger.info(f"[{self.session_id}] 页面加载完成，当前URL: {self.page.url}")

    def start(self, url: str):
        """启动浏览器会话（同步入口）"""
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        # 等待事件循环启动（最多5秒）
        for _ in range(50):
            if self.loop is not None:
                break
            time.sleep(0.1)
        if self.loop is None:
            raise Exception("事件循环启动超时")
        
        # 在事件循环中执行初始化
        future = asyncio.run_coroutine_threadsafe(self._init_browser(url), self.loop)
        future.result(timeout=90)

    def _ensure_loop(self):
        """确保事件循环存在"""
        if self.loop is None or self._closed:
            raise Exception("浏览器会话已关闭或未启动")

    def screenshot(self) -> str:
        """截图，返回base64编码的PNG图片"""
        self._ensure_loop()
        async def _shot():
            return await self.page.screenshot(type="jpeg", quality=75, full_page=False)
        future = asyncio.run_coroutine_threadsafe(_shot(), self.loop)
        img_bytes = future.result(timeout=30)
        return base64.b64encode(img_bytes).decode("utf-8")

    def click(self, x: float, y: float):
        """点击指定坐标"""
        self._ensure_loop()
        logger.info(f"[{self.session_id}] 点击坐标: ({x}, {y})")
        async def _click():
            await self.page.mouse.click(x, y)
            await self.page.wait_for_timeout(400)
        future = asyncio.run_coroutine_threadsafe(_click(), self.loop)
        future.result(timeout=20)

    def type(self, text: str):
        """在当前焦点元素输入文字"""
        self._ensure_loop()
        logger.info(f"[{self.session_id}] 输入文字: {text[:20]}...")
        async def _type():
            await self.page.keyboard.type(text, delay=30)
            await self.page.wait_for_timeout(300)
        future = asyncio.run_coroutine_threadsafe(_type(), self.loop)
        future.result(timeout=20)

    def press_key(self, key: str):
        """按键"""
        self._ensure_loop()
        async def _press():
            await self.page.keyboard.press(key)
            await self.page.wait_for_timeout(300)
        future = asyncio.run_coroutine_threadsafe(_press(), self.loop)
        future.result(timeout=15)

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
        """关闭浏览器会话（确保资源清理）"""
        if self._closed:
            return
        self._closed = True
        logger.info(f"[{self.session_id}] 正在关闭浏览器会话...")
        
        if self.loop and self.browser:
            async def _close():
                try:
                    if self.page:
                        await self.page.close()
                except:
                    pass
                try:
                    if self.context:
                        await self.context.close()
                except:
                    pass
                try:
                    if self.browser:
                        await self.browser.close()
                except:
                    pass
                try:
                    if self.playwright:
                        await self.playwright.stop()
                except:
                    pass
            try:
                future = asyncio.run_coroutine_threadsafe(_close(), self.loop)
                future.result(timeout=15)
            except Exception as e:
                logger.warning(f"[{self.session_id}] 关闭浏览器异常: {e}")
        
        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except:
                pass
        
        logger.info(f"[{self.session_id}] 浏览器会话已关闭")


# 平台登录页URL映射
PLATFORM_LOGIN_URLS = {
    "uhaozu": "https://www.uhaozu.com/login",
    "mima": "https://www.mimaapp.com/",
    "xubei": "https://passport.xubei.com/",
}


def _close_all_sessions():
    """关闭所有会话（在创建新会话前调用）"""
    global _active_session_id
    with _sessions_lock:
        session_ids = list(_sessions.keys())
    for sid in session_ids:
        try:
            close_session(sid)
        except Exception as e:
            logger.warning(f"关闭旧会话 {sid} 失败: {e}")
    _active_session_id = None
    time.sleep(1)  # 等待资源释放


def create_session(platform: str) -> Tuple[str, str]:
    """创建浏览器会话，返回(session_id, screenshot_base64)
    全局锁：同时只能有一个浏览器会话
    """
    global _active_session_id
    import uuid
    
    # 获取全局锁
    logger.info(f"等待浏览器全局锁...")
    acquired = _browser_lock.acquire(timeout=120)
    if not acquired:
        raise Exception("浏览器正忙，请稍后再试（当前有其他用户正在登录）")
    
    try:
        # 先关闭所有旧会话
        _close_all_sessions()
        
        # 获取登录页URL
        url = PLATFORM_LOGIN_URLS.get(platform)
        if not url:
            raise Exception(f"不支持的平台: {platform}")
        
        session_id = str(uuid.uuid4())[:8]
        logger.info(f"创建新浏览器会话: {session_id}, 平台: {platform}, URL: {url}")
        
        session = BrowserSession(session_id)
        try:
            session.start(url)
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            session.close()
            raise Exception(f"打开登录页失败: {e}")
        
        with _sessions_lock:
            _sessions[session_id] = {
                "session": session,
                "platform": platform,
                "created_at": time.time(),
            }
        _active_session_id = session_id
        
        screenshot = session.screenshot()
        logger.info(f"会话 {session_id} 创建成功，截图大小: {len(screenshot)}")
        return session_id, screenshot
        
    except Exception as e:
        _browser_lock.release()
        raise e


def get_session(session_id: str) -> Optional[BrowserSession]:
    """获取浏览器会话"""
    with _sessions_lock:
        data = _sessions.get(session_id)
        if data:
            return data["session"]
    return None


def close_session(session_id: str):
    """关闭浏览器会话"""
    global _active_session_id
    with _sessions_lock:
        data = _sessions.pop(session_id, None)
    
    if data:
        try:
            data["session"].close()
        except Exception as e:
            logger.warning(f"关闭会话 {session_id} 异常: {e}")
    
    if _active_session_id == session_id:
        _active_session_id = None
        # 释放全局锁
        try:
            _browser_lock.release()
        except:
            pass


def cleanup_expired_sessions(max_age: int = 300):
    """清理过期的会话（默认5分钟，缩短时间避免资源占用）"""
    now = time.time()
    expired = []
    with _sessions_lock:
        for sid, data in _sessions.items():
            if now - data["created_at"] > max_age:
                expired.append(sid)
    for sid in expired:
        logger.info(f"会话 {sid} 过期，自动关闭")
        close_session(sid)
    if expired:
        logger.info(f"清理了 {len(expired)} 个过期浏览器会话")
