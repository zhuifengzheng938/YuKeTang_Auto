"""Browser lifecycle, navigation, and login for yuketang_bot."""

import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from selectors import LOGIN_SUCCESS_SELECTORS, LOGIN_SUCCESS_TEXTS


class BrowserSession:
    """Manages Playwright browser, context, page lifecycle; login; and navigation."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.monitor_interval = 2.5 if quiet else 1.0
        self._pw = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    # -- async context manager -----------------------------------------------

    async def start(self):
        """Launch browser (prefer Edge)."""
        self._pw = await async_playwright().start()
        await self._launch_browser(prefer_edge=True)
        return self

    async def stop(self):
        """Close browser and stop Playwright."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    # -- launch / recovery ---------------------------------------------------

    async def _launch_browser(self, prefer_edge: bool, storage_state=None):
        launch_kwargs = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        last_error = None
        for use_edge in ([True, False] if prefer_edge else [False]):
            try:
                if use_edge:
                    self.browser = await self._pw.chromium.launch(channel="msedge", **launch_kwargs)
                    print("浏览器启动：使用 Microsoft Edge")
                else:
                    self.browser = await self._pw.chromium.launch(**launch_kwargs)
                    print("浏览器启动：Edge 会话异常，已回退到 Playwright Chromium")
                context_kwargs = {
                    "viewport": {"width": 1280, "height": 800},
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                }
                if storage_state:
                    context_kwargs["storage_state"] = storage_state
                self.context = await self.browser.new_context(**context_kwargs)
                self.page = await self.context.new_page()
                await self._apply_page_stealth(self.page)
                return
            except Exception as exc:
                last_error = exc
                if self.context:
                    await self.context.close()
                    self.context = None
                if self.browser:
                    await self.browser.close()
                    self.browser = None
                self.page = None
        raise last_error

    async def _apply_page_stealth(self, page: Page):
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
            Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
        """)

    async def _recover_browser_session(self):
        print("浏览器网络会话异常，正在重建浏览器并重试…")
        storage_state = None
        if self.context:
            try:
                storage_state = await self.context.storage_state()
            except Exception:
                storage_state = None
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        self.page = None
        await self._launch_browser(prefer_edge=False, storage_state=storage_state)

    @staticmethod
    def _is_socket_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(flag in text for flag in [
            "err_socket_not_connected",
            "err_internet_disconnected",
            "err_network_changed",
            "socket",
        ])

    # -- navigation ----------------------------------------------------------

    async def goto(self, url: str, *, timeout: int = 30000):
        last_error = None
        for attempt in range(2):
            try:
                await self.page.goto(url, timeout=timeout)
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0 and self._is_socket_error(exc):
                    await self._recover_browser_session()
                    continue
                raise
        if last_error:
            raise last_error

    async def go_back(self, *, timeout: int = 30000):
        last_error = None
        for attempt in range(2):
            try:
                await self.page.go_back(timeout=timeout)
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0 and self._is_socket_error(exc):
                    await self._recover_browser_session()
                    continue
                raise
        if last_error:
            raise last_error

    async def wait_ready(self, timeout: int = 15000):
        """Wait for page to be ready (best-effort — yuketang may have long-poll)."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

    # -- login ---------------------------------------------------------------

    async def login(self, timeout: int = 120):
        await self.goto("https://www.yuketang.cn/v2/web/index")
        await self.wait_ready()

        for sel in ["text=微信登录", "[class*='wechat']", "[class*='wx-login']"]:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=3000)
                if btn and await btn.is_visible():
                    await btn.click()
                    break
            except Exception:
                pass

        print("请用微信扫描二维码登录，等待中…")
        if await self._wait_for_login_success(timeout):
            print("登录成功！")
            return

        print("在等待时间内未检测到明确的登录成功信号，继续尝试访问课程页…")

    async def _wait_for_login_success(self, timeout: int) -> bool:
        try:
            await self.page.wait_for_function(
                """
                ({selectors, texts}) => {
                    const href = window.location.href;
                    const bodyText = document.body ? document.body.innerText : '';
                    const loggedIn = selectors.some(sel => document.querySelector(sel));
                    const loggedInByText = texts.some(text => bodyText.includes(text));
                    const leftLoginPage = !href.includes('login') && !href.includes('passport');
                    const enteredApp = href.includes('/course/') || href.includes('/lesson/') ||
                                       href.includes('/learn/') || href.includes('/home') ||
                                       href.includes('video-student');
                    return loggedIn || loggedInByText || (leftLoginPage && enteredApp);
                }
                """,
                {"selectors": LOGIN_SUCCESS_SELECTORS, "texts": LOGIN_SUCCESS_TEXTS},
                timeout=timeout * 1000,
            )
            return True
        except Exception:
            return False
