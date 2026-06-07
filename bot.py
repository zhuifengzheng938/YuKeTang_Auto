import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from solver import QuestionSolver

logger = logging.getLogger(__name__)

QUESTION_MODAL_SELECTORS = [
    ".question-modal", ".quiz-modal", ".exam-modal",
    ".el-dialog", ".ant-modal", ".ant-modal-content",
    "[class*='question-dialog']", "[class*='quiz-dialog']",
    "[class*='popup-question']", ".video-question",
    "[class*='danmu-question']", "[class*='inline-question']",
    "[class*='question']", "[class*='quiz']",
]
OPTION_SELECTORS = [
    ".option-item", ".choice-item", ".answer-option",
    ".el-radio", ".el-checkbox", ".ant-radio-wrapper", ".ant-checkbox-wrapper",
    "[class*='option-item']", "[class*='choice-item']", "[class*='option']",
    "label", "li.option", "li",
]
STEM_SELECTORS = [
    ".question-stem", ".stem", ".topic", ".subject", ".content",
    "[class*='question-stem']", "[class*='question-content']", "[class*='stem']", ".title",
]
SUBMIT_SELECTORS = [
    "button:has-text('提交')", "button:has-text('确认')", "button:has-text('确定')",
    "button:has-text('完成')", ".submit-btn", ".confirm-btn", "[class*='submit']",
    "[class*='confirm']", ".el-button--primary", ".ant-btn-primary",
]
SKIP_SELECTORS = [
    "button:has-text('跳过')", "button:has-text('关闭')", "button:has-text('知道了')",
    "button:has-text('取消')", "[class*='close']", ".el-dialog__close", ".ant-modal-close",
]
QUESTION_FEEDBACK_SELECTORS = [
    ".el-message", ".ant-message", ".ant-notification",
    "[class*='feedback']", "[class*='result']", "[class*='wrong']",
    "[class*='error']", "[class*='success']", "[class*='toast']",
]
LOGIN_SUCCESS_SELECTORS = [
    "[class*='user']", "[class*='avatar']", "img[class*='avatar']",
    "[class*='profile']", "[class*='logout']",
]
LOGIN_SUCCESS_TEXTS = ["退出登录", "个人中心"]
START_STUDY_SELECTORS = [
    "button:has-text('开始学习')", "button:has-text('继续学习')", "button:has-text('进入学习')",
    "button:has-text('去学习')", "a:has-text('开始学习')", "a:has-text('继续学习')",
    "a:has-text('进入学习')", "a:has-text('去学习')",
]
LESSON_ENTRY_SELECTORS = [
    "a[href*='video-student']", "a[href*='leafId']", "a[href*='lesson']", "a[href*='learn']",
    "[class*='lesson-item']", "[class*='chapter-item']", "[class*='video-item']", "[class*='leaf']",
]
SPEED_TRIGGER_SELECTORS = [
    "button:has-text('倍速')", "button:has-text('播放速度')", "[class*='speed']", "[class*='rate']",
    ".vjs-playback-rate", ".speed-box", ".speed-btn",
]
SPEED_OPTION_SELECTORS = [
    "text=/^16(?:\\.0+)?\\s*x$/i", "text=/^16(?:\\.0+)?倍$/i",
    "text=/^8(?:\\.0+)?\\s*x$/i", "text=/^8(?:\\.0+)?倍$/i",
    "text=/^6(?:\\.0+)?\\s*x$/i", "text=/^6(?:\\.0+)?倍$/i",
    "text=/^4(?:\\.0+)?\\s*x$/i", "text=/^4(?:\\.0+)?倍$/i",
    "text=/^3(?:\\.0+)?\\s*x$/i", "text=/^3(?:\\.0+)?倍$/i",
    "text=/^2(?:\\.0+)?\\s*x$/i", "text=/^2(?:\\.0+)?倍$/i",
    "text=/^1\\.5(?:0+)?\\s*x$/i", "text=/^1\\.5(?:0+)?倍$/i",
    "text=/^1\\.25(?:0+)?\\s*x$/i", "text=/^1\\.25(?:0+)?倍$/i",
]


def speed_option_selectors(rate: float):
    value = f"{rate:g}"
    escaped = re.escape(value)
    return [
        f"text=/^{escaped}(?:\\.0+)?\\s*x$/i",
        f"text=/^{escaped}(?:\\.0+)?倍$/i",
        f"text=/^(?:倍速\\s*)?{escaped}(?:\\.0+)?倍?$/i",
        f"text=/^(?:倍速\\s*)?{escaped}(?:\\.0+)?\\s*x$/i",
    ]


def speed_label(rate: float) -> str:
    return f"{rate:g}x"


def parse_speed_text(text: str):
    if not text:
        return None
    normalized = text.strip().lower().replace("倍速", "倍")
    normalized = normalized.replace("x", "").replace("倍", "")
    normalized = normalized.replace(" ", "")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


NEXT_LESSON_SELECTORS = [
    "button:has-text('下一节')", "a:has-text('下一节')",
    "button:has-text('下一个')", "a:has-text('下一个')",
    "button:has-text('下一课')", "a:has-text('下一课')",
    "button:has-text('下一视频')", "a:has-text('下一视频')",
]
CATALOG_TOGGLE_SELECTORS = [
    "button:has-text('目录')", "button:has-text('课程目录')",
    "button:has-text('章节')", "button:has-text('课时')",
    "button:has-text('展开')", "button:has-text('列表')",
    "a:has-text('目录')", "a:has-text('章节')",
]
EXPAND_TOGGLE_SELECTORS = [
    "text=展开",
    ".sub-info .gray span",
    "[class*='expand']",
    "[class*='unfold']",
    "[class*='J_expand']",
]
BACK_TO_CATALOG_SELECTORS = [
    "button:has-text('返回')", "a:has-text('返回')",
    "button:has-text('返回课程')", "a:has-text('返回课程')",
    "button:has-text('课程主页')", "a:has-text('课程主页')",
    "button:has-text('全部课时')", "a:has-text('全部课时')",
]
CATALOG_LESSON_SELECTOR = (
    "a[href*='video-student'], a[href*='leafId'], a[href*='lesson'], a[href*='learn'], "
    "[class*='lesson-item'], [class*='leaf-item'], [class*='video-item'], "
    "[class*='chapter-item'], [class*='activity__wrap'], [class*='content-box'] section"
)


class YuketangBot:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        web_search: bool = True,
        speed: float = 2.0,
        answer_delay: int = 3,
        quiet: bool = False,
    ):
        self.solver = QuestionSolver(api_key, base_url, model, web_search=web_search)
        self.quiet = quiet
        self.speed = min(speed, 1.25) if quiet else speed
        self.monitor_interval = 2.5 if quiet else 1.0
        self.answer_delay = answer_delay
        self._pw = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.course_scope = None
        self.visited_lesson_urls = set()
        self.visited_lesson_keys = set()
        self.catalog_url = None
        self._question_attempts = {}

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        await self._launch_browser(prefer_edge=True)
        return self

    async def __aexit__(self, *_):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

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

    async def _goto(self, url: str, *, timeout: int = 30000):
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

    async def _go_back(self, *, timeout: int = 30000):
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

    async def _wait_ready(self, timeout: int = 15000):
        # 雨课堂部分页面有长轮询/长连接，networkidle 可能永不触发。
        # 先等 DOM 就绪，再给 networkidle 一个短超时尝试，超时也不阻塞。
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

    async def login(self, timeout: int = 120):
        await self._goto("https://www.yuketang.cn/v2/web/index")
        await self._wait_ready()

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
                    const enteredApp = href.includes('/course/') || href.includes('/lesson/') || href.includes('/learn/') || href.includes('/home') || href.includes('video-student');
                    return loggedIn || loggedInByText || (leftLoginPage && enteredApp);
                }
                """,
                {"selectors": LOGIN_SUCCESS_SELECTORS, "texts": LOGIN_SUCCESS_TEXTS},
                timeout=timeout * 1000,
            )
            return True
        except Exception:
            return False

    async def watch_course(self, course_url: str):
        self.course_scope = self._course_scope_from_url(course_url)
        self.visited_lesson_urls.clear()
        self.visited_lesson_keys.clear()
        self.catalog_url = None
        await self._goto(course_url)
        await self._wait_ready()
        await asyncio.sleep(2)

        # 入口若是单视频页：先播当前视频，再设法回到课程目录页
        if await self._is_direct_video_page():
            print("入口是视频学习页，先播放当前视频，随后返回目录继续")
            self._remember_lesson_url(self.page.url)
            await self._watch_current_page_video()
            if not await self._go_to_catalog_page():
                print("无法返回课程目录，改用视频页内兜底查找下一节")
                await self._watch_next_lessons_in_same_course()
                return
        else:
            # 入口是课程页：先记住它作为目录页，再尝试点“开始学习/进入学习”
            self.catalog_url = self._normalize_lesson_url(self.page.url)
            await self._open_study_entry_if_needed()
            if await self._is_direct_video_page():
                self._remember_lesson_url(self.page.url)
                await self._watch_current_page_video()
                if not await self._go_to_catalog_page():
                    print("无法返回课程目录，改用视频页内兜底查找下一节")
                    await self._watch_next_lessons_in_same_course()
                    return

        # 现在应位于课程目录页，进入目录驱动循环
        if not self.catalog_url:
            self.catalog_url = self._normalize_lesson_url(self.page.url)
        await self._run_catalog_loop()

    async def _run_catalog_loop(self):
        print("进入目录驱动模式：从课程目录页依次处理未完成视频")
        empty_rounds = 0
        while True:
            await self._expand_catalog_if_needed()
            lesson = await self._pick_next_unfinished_lesson()
            if not lesson:
                empty_rounds += 1
                if empty_rounds >= 2:
                    print("课程目录中已无未完成的可播放视频，结束")
                    return
                # 偶尔目录尚未渲染完，重试一次
                await asyncio.sleep(2)
                continue
            empty_rounds = 0

            label = (lesson.get("text") or lesson.get("href") or "下一课时")[:60]
            print(f"打开课时: {label}")
            self._mark_lesson_visited(lesson)
            if not await self._open_catalog_lesson(lesson):
                print("  打开该课时失败，跳过")
                continue

            self._remember_lesson_url(self.page.url)
            await self._watch_current_page_video()

            if not await self._go_to_catalog_page():
                print("  播放后无法回到目录页，改用视频页内兜底继续")
                await self._watch_next_lessons_in_same_course()
                return

    async def _pick_next_unfinished_lesson(self):
        # 雨课堂目录可能是虚拟列表：如果停在底部，只能看到 31.x 之类靠后的课。
        # 所以每轮都先回到目录顶部，再逐屏向下找第一个未完成课时。
        await self._scroll_catalog_to_top()
        seen_pages = set()
        for _ in range(80):
            candidates = await self._collect_visible_lesson_candidates()
            if candidates:
                candidates.sort(key=lambda c: (round(c["top"] / 5), c["left"]))
                return candidates[0]

            pos = await self._catalog_scroll_signature()
            if pos in seen_pages:
                break
            seen_pages.add(pos)
            moved = await self._scroll_catalog_page_down()
            if not moved:
                break
        return None

    async def _collect_visible_lesson_candidates(self):
        candidates = []
        for scope in [self.page, *self.page.frames]:
            try:
                elements = await scope.query_selector_all(CATALOG_LESSON_SELECTOR)
            except Exception:
                continue
            for el in elements:
                try:
                    if not await el.is_visible():
                        continue
                    href = self._normalize_lesson_url(await el.get_attribute("href"))
                    text = self._clean_text(await el.inner_text())
                    classes = ((await el.get_attribute("class")) or "").lower()
                    if href and not self._url_in_course_scope(href):
                        continue
                    if "disabled" in classes or "lock" in classes:
                        continue
                    if self._is_summary_node(text, href):
                        continue
                    if self._lesson_text_is_finished(text):
                        continue
                    key = self._lesson_key(href, text)
                    if not key or key in self.visited_lesson_keys:
                        continue
                    if href and href in self.visited_lesson_urls:
                        continue
                    box = await el.bounding_box()
                    top = box["y"] if box else 1e9
                    left = box["x"] if box else 1e9
                    candidates.append({
                        "element": el, "href": href, "text": text,
                        "key": key, "top": top, "left": left,
                    })
                except Exception:
                    continue
        return candidates

    def _is_summary_node(self, text: str, href) -> bool:
        # 形如 "教学大纲 等 包含6章，31小节，共计43个学习单元 展开 进行中" 的根/章节汇总节点
        if not text:
            return False
        if href and "video-student" in href:
            return False
        summary_flags = ["包含", "小节", "学习单元", "共计", "教学大纲"]
        hits = sum(1 for f in summary_flags if f in text)
        # 命中两个及以上汇总特征，且没有具体视频链接，判定为汇总节点
        return hits >= 2 and not href

    async def _open_catalog_lesson(self, lesson) -> bool:
        href = lesson.get("href")
        if href:
            return await self._open_lesson_url(href)
        el = lesson.get("element")
        if not el:
            return False
        try:
            await el.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            await el.click()
            await self._wait_ready()
            await asyncio.sleep(2)
            return True
        except Exception:
            return False

    async def _go_to_catalog_page(self) -> bool:
        # 1) 直接回到记住的目录页 URL
        if self.catalog_url:
            try:
                await self._goto(self.catalog_url)
                await self._wait_ready()
                await asyncio.sleep(2)
                if not await self._is_direct_video_page():
                    await self._expand_catalog_if_needed()
                    return True
            except Exception:
                pass
        # 2) 点页面上的“返回/课程主页/全部课时”按钮
        if await self._return_to_catalog_page():
            if not self.catalog_url and not await self._is_direct_video_page():
                self.catalog_url = self._normalize_lesson_url(self.page.url)
            await self._expand_catalog_if_needed()
            return True
        # 3) 浏览器后退
        try:
            await self._go_back()
            await self._wait_ready()
            await asyncio.sleep(2)
            if not await self._is_direct_video_page():
                if not self.catalog_url:
                    self.catalog_url = self._normalize_lesson_url(self.page.url)
                await self._expand_catalog_if_needed()
                return True
        except Exception:
            pass
        return False

    async def _scroll_catalog_to_top(self):
        try:
            await self.page.evaluate(
                """
                () => {
                    const containers = document.querySelectorAll(
                        '.viewContainer, .logs-list, [class*="lesson"], [class*="catalog"], [class*="leaf"]'
                    );
                    containers.forEach(c => { c.scrollTop = 0; });
                    window.scrollTo(0, 0);
                }
                """
            )
            await asyncio.sleep(0.8)
        except Exception:
            pass

    async def _scroll_catalog_page_down(self) -> bool:
        try:
            return await self.page.evaluate(
                """
                () => {
                    const containers = Array.from(document.querySelectorAll(
                        '.viewContainer, .logs-list, [class*="lesson"], [class*="catalog"], [class*="leaf"]'
                    )).filter(c => c.scrollHeight > c.clientHeight + 5);
                    const target = containers.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || document.scrollingElement;
                    if (!target) return false;
                    const before = target.scrollTop;
                    target.scrollTop = before + Math.max(300, Math.floor(target.clientHeight * 0.8));
                    if (target === document.scrollingElement) window.scrollTo(0, target.scrollTop);
                    return target.scrollTop !== before;
                }
                """
            )
        except Exception:
            return False
        finally:
            await asyncio.sleep(0.8)

    async def _catalog_scroll_signature(self):
        try:
            return await self.page.evaluate(
                """
                () => {
                    const containers = Array.from(document.querySelectorAll(
                        '.viewContainer, .logs-list, [class*="lesson"], [class*="catalog"], [class*="leaf"]'
                    )).filter(c => c.scrollHeight > c.clientHeight + 5);
                    const target = containers.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || document.scrollingElement;
                    if (!target) return 'none';
                    return `${Math.round(target.scrollTop)}:${Math.round(target.scrollHeight)}:${Math.round(target.clientHeight)}`;
                }
                """
            )
        except Exception:
            return "unknown"

    def _lesson_text_is_finished(self, text: str) -> bool:
        if not text:
            return False
        if any(flag in text for flag in ["未完成", "未学习", "未开始", "未读", "进行中"]):
            return False
        return any(flag in text for flag in [
            "已完成", "学习完成", "完成学习", "观看完成", "已看完",
            "已学完", "已学习", "已读", "100%", "99%", "98%",
        ])

    def _lesson_key(self, href, text):
        if href:
            return f"url::{href}"
        if text:
            return f"text::{text[:80]}"
        return None

    def _mark_lesson_visited(self, lesson):
        key = lesson.get("key")
        if key:
            self.visited_lesson_keys.add(key)
        href = lesson.get("href")
        if href:
            self.visited_lesson_urls.add(href)

    async def _open_study_entry_if_needed(self):
        if await self._is_direct_video_page():
            return
        for sel in START_STUDY_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await self._wait_ready()
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue

    async def _open_first_lesson_entry(self) -> bool:
        for sel in LESSON_ENTRY_SELECTORS:
            try:
                nodes = await self.page.query_selector_all(sel)
            except Exception:
                continue
            for node in nodes:
                try:
                    if not await node.is_visible():
                        continue
                    href = await node.get_attribute("href")
                    if href:
                        await self._goto(href)
                    else:
                        await node.click()
                    await self._wait_ready()
                    await asyncio.sleep(2)
                    return True
                except Exception:
                    continue
        return False

    async def _collect_lessons(self) -> list:
        links = await self.page.eval_on_selector_all(
            "a[href*='lesson'], a[href*='video'], a[href*='video-student'], a[href*='leafId'], "
            "[class*='lesson-item'] a, [class*='video-item'] a",
            "els => els.map(e => e.href).filter(Boolean)",
        )
        if links:
            return list(dict.fromkeys(links))

        items = await self.page.query_selector_all(
            "[class*='lesson-item'], [class*='chapter-item'], [class*='video-item']"
        )
        return [f"__index__{i}" for i in range(len(items))]

    async def _is_direct_video_page(self) -> bool:
        url = self.page.url
        if any(keyword in url for keyword in ["video-student", "/lesson/", "/learn/"]):
            return True
        return await self._find_video() is not None

    async def _watch_lesson_url(self, target: str):
        if target.startswith("__index__"):
            idx = int(target.split("__index__")[1])
            items = await self.page.query_selector_all(
                "[class*='lesson-item'], [class*='chapter-item'], [class*='video-item']"
            )
            if idx < len(items):
                await items[idx].click()
                await self._wait_ready()
        else:
            self._remember_lesson_url(target)
            await self._goto(target)
            await self._wait_ready()

        await asyncio.sleep(2)
        self._remember_lesson_url(self.page.url)
        await self._watch_current_page_video()

    async def _watch_current_page_video(self):
        self._remember_lesson_url(self.page.url)
        if await self._page_shows_completion():
            print("  页面显示已完成，跳过当前课时")
            return
        video = await self._find_video()
        if not video:
            print("  未找到视频，跳过")
            return

        selected_ui_rate = False
        if not self.quiet:
            selected_ui_rate = await self._select_target_speed()
        else:
            print(f"  安静模式：使用 {speed_label(self.speed)}，跳过页面倍速选择")
        states = await self._set_speed()
        self._print_speed_states(states, selected_ui_rate)
        await self._override_visibility()
        await self._ensure_playing()
        await self._monitor_until_done()

    async def _watch_next_lessons_in_same_course(self):
        while True:
            next_url = await self._advance_to_next_lesson_in_same_course()
            if not next_url:
                print("同一课程下未找到下一个可播放视频，结束")
                return
            print(f"自动切换到下一节: {next_url}")
            self._remember_lesson_url(next_url)
            await self._watch_current_page_video()

    async def _advance_to_next_lesson_in_same_course(self):
        await self._expand_catalog_if_needed()

        next_url = await self._click_explicit_next_lesson()
        if next_url:
            return next_url

        next_url = await self._find_next_lesson_after_current()
        if next_url and await self._open_lesson_url(next_url):
            return self._normalize_lesson_url(self.page.url) or next_url

        next_url = await self._click_next_lesson_item_after_current()
        if next_url:
            return next_url

        if await self._return_to_catalog_page():
            await self._expand_catalog_if_needed()

            next_url = await self._find_next_lesson_after_current()
            if next_url and await self._open_lesson_url(next_url):
                return self._normalize_lesson_url(self.page.url) or next_url

            next_url = await self._click_next_lesson_item_after_current()
            if next_url:
                return next_url

        candidates = await self._collect_navigation_candidates_from_scopes()
        for item in candidates:
            href = self._normalize_lesson_url(item.get("href"))
            if not href:
                continue
            if not self._url_in_course_scope(href):
                continue
            if href in self.visited_lesson_urls:
                continue
            text = self._clean_text(item.get("text") or "")
            classes = (item.get("classes") or "").lower()
            aria_current = (item.get("ariaCurrent") or "").lower()
            aria_disabled = (item.get("ariaDisabled") or "").lower()
            if aria_current == "page" or "current" in classes or "active" in classes:
                continue
            if aria_disabled == "true" or "disabled" in classes or "lock" in classes:
                continue
            if any(flag in text for flag in ["已完成", "100%", "完成"]):
                continue
            if await self._open_lesson_url(href):
                return self._normalize_lesson_url(self.page.url) or href
        return None

    async def _expand_catalog_if_needed(self):
        # 先点一次顶层目录/列表入口（如果有）
        for sel in CATALOG_TOGGLE_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                continue
        # 再把所有"展开"标志尽量全部点开（雨课堂章节默认折叠，视频藏在小节里）
        await self._expand_all_sections()

    async def _expand_all_sections(self):
        for _ in range(8):  # 多轮：展开后可能出现新的可展开节点
            clicked = 0
            for scope in [self.page, *self.page.frames]:
                for sel in EXPAND_TOGGLE_SELECTORS:
                    try:
                        nodes = await scope.query_selector_all(sel)
                    except Exception:
                        continue
                    for node in nodes:
                        try:
                            if not await node.is_visible():
                                continue
                            text = self._clean_text(await node.inner_text())
                            # 只点"展开"，不要误点"收起/收缩"
                            if text and ("收起" in text or "收缩" in text):
                                continue
                            await node.click()
                            clicked += 1
                            await asyncio.sleep(0.3)
                        except Exception:
                            continue
            if clicked == 0:
                break
            await asyncio.sleep(0.5)

    async def _return_to_catalog_page(self) -> bool:
        for sel in BACK_TO_CATALOG_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await self._wait_ready()
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue
        return False

    async def _click_explicit_next_lesson(self):
        for sel in NEXT_LESSON_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if not btn or not await btn.is_visible():
                    continue
                href = await btn.get_attribute("href")
                if href:
                    normalized = self._normalize_lesson_url(href)
                    if normalized and await self._open_lesson_url(normalized):
                        return self._normalize_lesson_url(self.page.url) or normalized
                    continue
                await btn.click()
                await self._wait_ready()
                await asyncio.sleep(2)
                current = self._normalize_lesson_url(self.page.url)
                if current and current not in self.visited_lesson_urls:
                    return current
            except Exception:
                continue
        return None

    async def _find_next_lesson_after_current(self):
        current = self._normalize_lesson_url(self.page.url)
        if not current:
            return None
        candidates = await self.page.eval_on_selector_all(
            "a[href*='video-student'], a[href*='leafId'], a[href*='lesson'], a[href*='learn']",
            """
            els => els.map(el => ({
                href: el.href,
                text: (el.innerText || '').trim(),
                classes: el.className || '',
                ariaCurrent: el.getAttribute('aria-current') || '',
            }))
            """,
        )
        seen_current = False
        for item in candidates:
            href = self._normalize_lesson_url(item.get("href"))
            if not href:
                continue
            if not self._url_in_course_scope(href):
                continue
            text = self._clean_text(item.get("text") or "")
            classes = (item.get("classes") or "").lower()
            aria_current = (item.get("ariaCurrent") or "").lower()
            is_current = href == current or aria_current == "page" or "current" in classes or "active" in classes
            if is_current:
                seen_current = True
                continue
            if not seen_current:
                continue
            if href in self.visited_lesson_urls:
                continue
            if any(flag in text for flag in ["已完成", "100%", "完成"]):
                continue
            return href
        return None

    async def _click_next_lesson_item_after_current(self):
        current = self._normalize_lesson_url(self.page.url)
        if not current:
            return None
        selectors = ", ".join(LESSON_ENTRY_SELECTORS)
        items = await self.page.query_selector_all(selectors)
        seen_current = False
        for item in items:
            try:
                if not await item.is_visible():
                    continue
                href = self._normalize_lesson_url(await item.get_attribute("href"))
                text = self._clean_text(await item.inner_text())
                classes = ((await item.get_attribute("class")) or "").lower()
                is_current = href == current or "current" in classes or "active" in classes
                if is_current:
                    seen_current = True
                    continue
                if not seen_current:
                    continue
                if any(flag in text for flag in ["已完成", "100%", "完成"]):
                    continue
                await item.click()
                await self._wait_ready()
                await asyncio.sleep(2)
                next_url = self._normalize_lesson_url(self.page.url)
                if next_url and next_url not in self.visited_lesson_urls:
                    return next_url
            except Exception:
                continue
        return None

    async def _open_lesson_url(self, href: str) -> bool:
        if not href:
            return False
        try:
            await self._goto(href)
            await self._wait_ready()
            await asyncio.sleep(2)
            return True
        except Exception:
            return False

    async def _collect_navigation_candidates_from_scopes(self):
        script = """
            els => els.map(el => ({
                href: el.href,
                text: (el.innerText || '').trim(),
                classes: el.className || '',
                ariaCurrent: el.getAttribute('aria-current') || '',
                ariaDisabled: el.getAttribute('aria-disabled') || '',
            }))
        """
        selector = "a[href*='video-student'], a[href*='leafId'], a[href*='lesson'], a[href*='learn']"
        candidates = []
        for scope in [self.page, *self.page.frames]:
            try:
                items = await scope.eval_on_selector_all(selector, script)
                if items:
                    candidates.extend(items)
            except Exception:
                continue
        return candidates

    async def _find_video(self):
        try:
            return await self.page.wait_for_selector("video", timeout=10000)
        except Exception:
            pass
        for frame in self.page.frames:
            try:
                v = await frame.query_selector("video")
                if v:
                    return v
            except Exception:
                pass
        return None

    async def _set_speed(self):
        js = f"""
            () => {{
                const targetRate = {self.speed};
                const seenRoots = new Set();
                const medias = [];

                function collect(root) {{
                    if (!root || seenRoots.has(root)) return;
                    seenRoots.add(root);
                    try {{
                        if (root.querySelectorAll) {{
                            root.querySelectorAll('video, audio').forEach(m => medias.push(m));
                            root.querySelectorAll('*').forEach(el => {{
                                if (el.shadowRoot) collect(el.shadowRoot);
                            }});
                        }}
                    }} catch (_) {{}}
                }}

                function lockRate(media) {{
                    try {{
                        media.defaultPlaybackRate = targetRate;
                        media.playbackRate = targetRate;
                        media.preservesPitch = true;
                    }} catch (_) {{}}
                }}

                collect(document);
                for (const m of medias) {{
                    try {{
                        lockRate(m);
                        if (!m.__yuketangRateLockInstalled) {{
                            const handler = () => lockRate(m);
                            m.addEventListener('play', handler, true);
                            m.addEventListener('playing', handler, true);
                            m.addEventListener('loadedmetadata', handler, true);
                            m.addEventListener('canplay', handler, true);
                            m.addEventListener('ratechange', handler, true);
                            m.__yuketangRateLockInstalled = true;
                        }}
                        if (!m.__yuketangRateLockTimer) {{
                            m.__yuketangRateLockTimer = setInterval(() => lockRate(m), 500);
                        }}
                        m.dispatchEvent(new Event('ratechange', {{ bubbles: true }}));
                    }} catch (_) {{}}
                }}
                return medias.map(m => ({{
                    tag: m.tagName,
                    rate: m.playbackRate,
                    defaultRate: m.defaultPlaybackRate,
                    currentTime: m.currentTime || 0,
                    paused: !!m.paused,
                }}));
            }}
        """
        states = []
        try:
            result = await self.page.evaluate(js)
            if result:
                states.extend(result)
        except Exception:
            pass
        for frame in self.page.frames:
            try:
                result = await frame.evaluate(js)
                if result:
                    states.extend(result)
            except Exception:
                pass
        return states

    def _print_speed_states(self, states, selected_ui_rate: bool = False):
        if not states:
            print(f"  未检测到可设置倍速的媒体元素，目标倍速 {self.speed}x")
            return

        def approx_target(rate):
            try:
                return abs(float(rate) - float(self.speed)) < 0.05
            except Exception:
                return False

        active_states = [
            state for state in states
            if not state.get("paused") or float(state.get("currentTime") or 0) > 0.1
        ]
        relevant_states = active_states or states

        current_rates = []
        default_rates = []
        matched = 0
        for state in relevant_states:
            rate = state.get("rate")
            default_rate = state.get("defaultRate")
            if rate is not None:
                current_rates.append(str(rate))
                if approx_target(rate):
                    matched += 1
            if default_rate is not None:
                default_rates.append(str(default_rate))

        shown_current = ", ".join(current_rates[:5]) if current_rates else "未知"
        shown_default = ", ".join(default_rates[:5]) if default_rates else "未知"
        if matched and matched == len(relevant_states):
            print(
                f"  已确认媒体倍速：目标 {self.speed}x，当前 {shown_current}，"
                f"defaultPlaybackRate {shown_default}"
            )
            return

        if selected_ui_rate:
            print(
                f"  页面倍速菜单已点击，但媒体当前仍为 {shown_current}，"
                f"defaultPlaybackRate {shown_default}，播放器可能已重置倍速"
            )
            return

        print(
            f"  已尝试写入媒体倍速：目标 {self.speed}x，当前 {shown_current}，"
            f"defaultPlaybackRate {shown_default}"
        )

    async def _select_target_speed(self):
        for scope in [self.page, *self.page.frames]:
            try:
                if await self._select_target_speed_in_scope(scope):
                    print(f"  已切换到页面倍速 {speed_label(self.speed)}")
                    return True
            except Exception:
                continue
        print(f"  未在页面倍速菜单找到 {speed_label(self.speed)}，改用媒体倍速写入")
        return False

    async def _select_target_speed_in_scope(self, scope) -> bool:
        target_selectors = speed_option_selectors(self.speed)
        for trigger_sel in SPEED_TRIGGER_SELECTORS:
            try:
                triggers = await scope.query_selector_all(trigger_sel)
            except Exception:
                continue
            for trigger in triggers:
                try:
                    if not await trigger.is_visible():
                        continue
                    await trigger.click()
                    await asyncio.sleep(0.5)

                    for option_sel in target_selectors:
                        option = await scope.query_selector(option_sel)
                        if option and await option.is_visible():
                            await option.click()
                            await asyncio.sleep(0.5)
                            return True

                    candidates = []
                    for sel in [
                        "text=/\\d+(?:\\.\\d+)?\\s*(?:x|倍)/i",
                        "[class*='rate']",
                        "[class*='speed'] li",
                        "[class*='speed'] button",
                        "[class*='speed'] span",
                    ]:
                        try:
                            nodes = await scope.query_selector_all(sel)
                        except Exception:
                            continue
                        for node in nodes:
                            try:
                                if not await node.is_visible():
                                    continue
                                text = (await node.inner_text()).strip()
                            except Exception:
                                continue
                            value = parse_speed_text(text)
                            if value is None:
                                continue
                            candidates.append((abs(value - self.speed), node, text, value))

                    if candidates:
                        candidates.sort(key=lambda item: item[0])
                        _, node, text, value = candidates[0]
                        await node.click()
                        await asyncio.sleep(0.5)
                        if abs(value - self.speed) < 0.01:
                            print(f"  页面倍速菜单命中项：{text}")
                        else:
                            print(f"  页面倍速菜单未找到精确 {speed_label(self.speed)}，改点最接近项：{text}")
                        return True
                except Exception:
                    continue
        return False

    async def _override_visibility(self):
        await self.page.evaluate("""
            Object.defineProperty(document, 'hidden',
                {get: () => false, configurable: true});
            Object.defineProperty(document, 'visibilityState',
                {get: () => 'visible', configurable: true});
            document.dispatchEvent(new Event('visibilitychange'));
        """)

    async def _ensure_playing(self):
        js = """
            () => {
                const videos = Array.from(document.querySelectorAll('video'));
                for (const v of videos) {
                    if (v.paused) v.play().catch(() => {});
                }
            }
        """
        await self.page.evaluate(js)
        for frame in self.page.frames:
            try:
                await frame.evaluate(js)
            except Exception:
                pass

    async def _monitor_until_done(self):
        print("  监控视频播放中…")
        stall_count = 0
        last_time = -1.0
        missing_video_count = 0

        while True:
            # 雨课堂播放器可能会把 playbackRate 重置回 1x，所以每轮都重新写入目标倍速。
            await self._set_speed()

            if await self._page_shows_completion():
                print("  页面显示已完成，结束当前课时")
                return

            if await self._check_and_handle_question():
                await self._ensure_playing()
                await self._set_speed()
                stall_count = 0
                continue

            video_state = await self._get_video_state()
            if video_state["missing"]:
                missing_video_count += 1
                if await self._page_shows_completion():
                    print("  页面显示已完成，结束当前课时")
                    return
                if missing_video_count >= 5:
                    print("  视频元素暂时消失，结束当前课时")
                    return
                await asyncio.sleep(self.monitor_interval)
                continue

            missing_video_count = 0
            if video_state["done"]:
                print(f"  视频播放完成！{self._format_video_state(video_state)}")
                return

            cur = video_state["current_time"]
            if abs(cur - last_time) < 0.1:
                stall_count += 1
                if stall_count >= 5:
                    print(f"  检测到播放停滞，尝试恢复{self._format_video_state(video_state)}")
                    await self._ensure_playing()
                    await self._set_speed()
                    stall_count = 0
            else:
                stall_count = 0
            last_time = cur

            await asyncio.sleep(self.monitor_interval)

    async def _check_and_handle_question(self) -> bool:
        for scope in [self.page, *self.page.frames]:
            modal = await self._find_visible_modal(scope)
            if modal:
                print("  检测到题目弹窗")
                await self._handle_question(modal)
                return True
        return False

    async def _handle_question(self, modal):
        await asyncio.sleep(1)

        stem = await self._extract_stem(modal)
        if not stem:
            print("  无法提取题目，尝试跳过")
            await self._try_skip(modal)
            return

        qkey = stem[:120]
        state = self._question_attempts.setdefault(qkey, {"attempts": 0, "failed_answers": set()})
        if state["attempts"] >= 3:
            print(f"  同一题已尝试 {state['attempts']} 次仍未通过，强制跳过以免卡死")
            await self._force_dismiss_question(modal)
            return

        print(f"  题目: {stem[:80]}…")
        q_type, options = await self._extract_type_and_options(modal)
        print(f"  题型: {q_type}  选项: {options}")

        if q_type == "unknown":
            print("  无法识别题型，尝试跳过")
            await self._try_skip(modal)
            return

        await asyncio.sleep(self.answer_delay)
        failed_answers = sorted(state["failed_answers"])
        try:
            answer = self.solver.solve(
                stem,
                options,
                q_type,
                failed_answers=failed_answers,
                attempt_no=state["attempts"] + 1,
            )
        except Exception as exc:
            print(f"  调用解题器失败: {exc}")
            await self._try_skip(modal)
            return
        print(f"  答案: {answer}")

        normalized = self.solver.normalize_answer(answer, q_type, options)
        result = await self._submit(modal, q_type, options, answer)
        if result == "submitted":
            state["attempts"] = 0
            state["failed_answers"].clear()
            return
        if result == "retry":
            state["attempts"] += 1
            if normalized:
                state["failed_answers"].add(normalized)
                print(f"  已记录错误答案，稍后重试: {normalized}")
            else:
                print("  提交未通过，但本次答案无法规范化记录")
            return

        print("  未确认提交结果，保留当前页面供人工检查")

    async def _force_dismiss_question(self, modal):
        # 优先点关闭/跳过类按钮；都不行就移除该弹窗节点，避免反复触发
        for sel in SKIP_SELECTORS:
            try:
                btn = await modal.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                continue
        try:
            await modal.evaluate("el => el.remove()")
        except Exception:
            pass

    async def _extract_stem(self, modal) -> str:
        for sel in STEM_SELECTORS:
            el = await modal.query_selector(sel)
            if el:
                t = self._clean_text(await el.inner_text())
                if t:
                    return t
        return self._clean_text(await modal.inner_text())

    async def _extract_type_and_options(self, modal):
        modal_text = self._clean_text(await modal.inner_text())
        option_els = await self._find_option_elements(modal)
        options = []
        for el in option_els:
            text = self._clean_option_text(await el.inner_text())
            if text and text not in options:
                options.append(text)

        has_input = bool(await modal.query_selector("input[type='text'], textarea, [contenteditable='true']"))
        lowered = modal_text.lower()

        if "多选" in modal_text:
            return "multiple", options
        if any(word in modal_text for word in ["判断", "正确", "错误", "对错"]):
            if len(options) == 2 or not options:
                return "truefalse", options
        if "填空" in modal_text or has_input:
            return "fillin", options
        if "单选" in modal_text and options:
            return "single", options
        if len(options) >= 2:
            joined = "".join(options).lower()
            if len(options) == 2 and any(word in joined for word in ["正确", "错误", "true", "false", "对", "错"]):
                return "truefalse", options
            if "multiple" in lowered:
                return "multiple", options
            return "single", options
        if has_input:
            return "fillin", options
        return "unknown", options

    async def _submit(self, modal, q_type: str, options: list, answer):
        option_els = await self._find_option_elements(modal)

        if q_type == "single":
            if not isinstance(answer, int) or not (0 <= answer < len(option_els)):
                print("  单选答案无效，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            if not await self._click_option_by_index(modal, answer):
                print("  单选点击失败，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            await asyncio.sleep(0.5)

        elif q_type == "truefalse":
            idx = None
            if isinstance(answer, bool):
                idx = 0 if answer else 1
            elif isinstance(answer, int):
                idx = answer
            if idx is None or not (0 <= idx < len(option_els)):
                print("  判断题答案无效，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            if not await self._click_option_by_index(modal, idx):
                print("  判断题点击失败，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            await asyncio.sleep(0.5)

        elif q_type == "multiple":
            if not isinstance(answer, list):
                print("  多选答案无效，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            valid_indices = []
            for idx in answer:
                if isinstance(idx, int) and 0 <= idx < len(option_els) and idx not in valid_indices:
                    valid_indices.append(idx)
            if not valid_indices:
                print("  多选答案为空，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            for idx in valid_indices:
                if not await self._click_option_by_index(modal, idx):
                    print(f"  多选选项 {idx} 点击失败，尝试跳过")
                    await self._try_skip(modal)
                    return "unknown"
                await asyncio.sleep(0.3)

        elif q_type == "fillin":
            if not isinstance(answer, str) or not answer.strip():
                print("  填空答案为空，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            inp = await modal.query_selector("input[type='text'], textarea, [contenteditable='true']")
            if not inp:
                print("  未找到填空输入框，尝试跳过")
                await self._try_skip(modal)
                return "unknown"
            if await inp.get_attribute("contenteditable") == "true":
                await inp.fill("")
                await inp.type(answer.strip())
            else:
                await inp.fill(answer.strip())

        return await self._click_submit(modal)

    async def _click_option_by_index(self, modal, index: int) -> bool:
        for _ in range(3):
            try:
                option_els = await self._find_option_elements(modal)
                if not (0 <= index < len(option_els)):
                    return False
                if await self._safe_click(option_els[index]):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.4)
        return False

    async def _safe_click(self, el) -> bool:
        # 优先点击内部真正可交互控件，避免只点到外层文本容器
        try:
            inner = await el.query_selector(
                "input, label, [role='radio'], [role='checkbox'], "
                ".el-radio, .el-checkbox, .el-radio__input, .el-checkbox__input, "
                ".ant-radio, .ant-checkbox"
            )
            if inner and await inner.is_visible():
                try:
                    await inner.click(timeout=3000)
                    return True
                except Exception:
                    await inner.evaluate("node => { node.scrollIntoView({block: 'center'}); node.click(); }")
                    return True
        except Exception:
            pass

        try:
            if await el.is_visible():
                await el.click(timeout=3000)
                return True
        except Exception:
            pass
        try:
            await el.evaluate("node => { node.scrollIntoView({block: 'center'}); node.click(); }")
            return True
        except Exception:
            return False

    async def _try_skip(self, modal):
        for sel in SUBMIT_SELECTORS + SKIP_SELECTORS:
            btn = await modal.query_selector(sel)
            if btn and await btn.is_visible():
                await self._safe_click(btn)
                return

    async def _find_visible_modal(self, scope):
        for sel in QUESTION_MODAL_SELECTORS:
            try:
                nodes = await scope.query_selector_all(sel)
            except Exception:
                continue
            for node in nodes:
                try:
                    if await node.is_visible():
                        text = self._clean_text(await node.inner_text())
                        if any(keyword in text for keyword in ["题", "单选", "多选", "判断", "填空", "提交"]):
                            return node
                except Exception:
                    continue
        return None

    async def _find_option_elements(self, modal):
        best = []
        for sel in OPTION_SELECTORS:
            try:
                els = await modal.query_selector_all(sel)
            except Exception:
                continue
            filtered = []
            for el in els:
                try:
                    text = self._clean_option_text(await el.inner_text())
                    if text:
                        filtered.append((el, text))
                except Exception:
                    continue
            if not filtered:
                continue
            # 单个元素却包含多个选项标记 → 这是"装着全部选项的容器"，跳过
            if len(filtered) == 1 and self._count_option_markers(filtered[0][1]) >= 2:
                continue
            # 多个独立选项：直接采用（正常单选/多选至少 2 个选项）
            if len(filtered) >= 2:
                return [el for el, _ in filtered]
            # 只有 1 个且不像 blob：先记下，作为兜底
            if not best:
                best = [el for el, _ in filtered]
        return best

    @staticmethod
    def _count_option_markers(text: str) -> int:
        # 统计形如 "A " "A." "A、" 的选项标记数量，用于识别整块选项 blob
        return len(re.findall(r"(?:^|\s)[A-H](?:[\.、\．\:：\s])", " " + text))

    async def _click_submit(self, modal):
        for sel in SUBMIT_SELECTORS:
            btn = await modal.query_selector(sel)
            if not btn or not await btn.is_visible():
                continue
            if not await self._safe_click(btn):
                continue
            await asyncio.sleep(1)

            try:
                if not await modal.is_visible():
                    return "submitted"
            except Exception:
                return "submitted"

            feedback = await self._detect_question_feedback(modal)
            if feedback == "wrong":
                return "retry"
            if feedback == "correct":
                return "submitted"

            try:
                still_visible = await btn.is_visible()
                if not still_visible:
                    return "submitted"
            except Exception:
                return "submitted"
        return "unknown"

    async def _detect_question_feedback(self, modal):
        texts = []
        for scope in [modal, self.page, *self.page.frames]:
            try:
                text = self._clean_text(await scope.inner_text())
            except Exception:
                continue
            if text:
                texts.append(text)
        merged = " ".join(texts)
        wrong_markers = [
            "回答错误", "答错", "不正确", "未答对", "重新作答", "请重试", "再试一次", "重新提交",
        ]
        correct_markers = [
            "回答正确", "答对", "恭喜答对", "提交成功", "回答已提交",
        ]
        if any(marker in merged for marker in wrong_markers):
            return "wrong"
        if any(marker in merged for marker in correct_markers):
            return "correct"

        for scope in [self.page, *self.page.frames]:
            for sel in QUESTION_FEEDBACK_SELECTORS:
                try:
                    nodes = await scope.query_selector_all(sel)
                except Exception:
                    continue
                for node in nodes:
                    try:
                        if not await node.is_visible():
                            continue
                        text = self._clean_text(await node.inner_text())
                    except Exception:
                        continue
                    if any(marker in text for marker in wrong_markers):
                        return "wrong"
                    if any(marker in text for marker in correct_markers):
                        return "correct"
        return "unknown"

    @staticmethod
    def _format_video_state(video_state) -> str:
        if not video_state or video_state.get("missing"):
            return ""
        fields = [
            f" source={video_state.get('source', 'unknown')}",
            f" paused={video_state.get('paused')}",
            f" current={video_state.get('current_time')}",
            f" duration={video_state.get('duration')}",
            f" readyState={video_state.get('ready_state')}",
            f" ended={video_state.get('ended')}",
        ]
        return " |" + " ".join(fields)

    async def _get_video_state(self):
        script = """
            () => {
                const videos = Array.from(document.querySelectorAll('video'));
                if (!videos.length) {
                    return {missing: true, done: false, current_time: 0};
                }

                const candidates = videos.map((v, index) => {
                    const rect = typeof v.getBoundingClientRect === 'function'
                        ? v.getBoundingClientRect()
                        : {width: 0, height: 0};
                    const style = window.getComputedStyle ? window.getComputedStyle(v) : null;
                    const visible = !!(
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none'
                    );
                    const duration = Number.isFinite(v.duration) ? v.duration : 0;
                    const currentTime = Number.isFinite(v.currentTime) ? v.currentTime : 0;
                    const playbackRate = Number.isFinite(v.playbackRate) ? v.playbackRate : 0;
                    const score =
                        (visible ? 1000 : 0) +
                        Math.min(duration, 36000) +
                        Math.min(currentTime, 36000) +
                        (!v.paused ? 500 : 0) +
                        (v.readyState || 0) * 20 +
                        (v.ended ? -2000 : 0);

                    return {
                        index,
                        visible,
                        paused: !!v.paused,
                        ended: !!v.ended,
                        current_time: currentTime,
                        duration,
                        ready_state: v.readyState || 0,
                        playback_rate: playbackRate,
                        score,
                    };
                });

                candidates.sort((a, b) => b.score - a.score);
                const v = candidates[0];
                return {
                    missing: false,
                    source: `video[${v.index}]`,
                    done: !!(
                        v.ended ||
                        (v.duration > 0 && v.current_time >= Math.max(v.duration - 0.5, v.duration * 0.995))
                    ),
                    current_time: v.current_time,
                    duration: v.duration,
                    paused: v.paused,
                    ready_state: v.ready_state,
                    ended: v.ended,
                    playback_rate: v.playback_rate,
                    candidates,
                };
            }
        """
        for scope in [self.page, *self.page.frames]:
            try:
                state = await scope.evaluate(script)
                if state and not state.get("missing"):
                    state.setdefault("source", "unknown")
                    return state
            except Exception:
                continue
        return {
            "missing": True,
            "done": False,
            "current_time": 0,
            "duration": 0,
            "paused": True,
            "ready_state": 0,
            "ended": False,
            "source": "none",
        }

    async def _page_shows_completion(self) -> bool:
        selectors = [
            ".progress-wrap", ".statistics-box", ".status", ".aside",
            "[class*='progress']", "[class*='status']", "[class*='complete']",
            "[class*='finished']", "[class*='done']",
        ]
        for scope in [self.page, *self.page.frames]:
            for sel in selectors:
                try:
                    nodes = await scope.query_selector_all(sel)
                except Exception:
                    continue
                for node in nodes:
                    try:
                        if await node.is_visible():
                            text = self._clean_text(await node.inner_text())
                            if self._lesson_text_is_finished(text):
                                return True
                    except Exception:
                        continue
        try:
            body_text = self._clean_text(await self.page.inner_text("body"))
            return self._lesson_text_is_finished(body_text)
        except Exception:
            return False

    def _course_scope_from_url(self, url: str):
        normalized = self._normalize_lesson_url(url)
        if not normalized:
            return None
        parsed = urlparse(normalized)
        segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
        query = parse_qs(parsed.query)
        course_id = None
        # video-student/<classroom_id>/<leaf_id>
        if "video-student" in segments:
            idx = segments.index("video-student")
            if idx > 0:
                course_id = segments[idx - 1]
        # studentLog/<classroom_id>
        if not course_id and "studentLog" in segments:
            idx = segments.index("studentLog")
            if idx + 1 < len(segments):
                course_id = segments[idx + 1]
        # course/<id>
        if not course_id and "course" in segments:
            idx = segments.index("course")
            if idx + 1 < len(segments):
                course_id = segments[idx + 1]
        # 最后用 classroom_id 查询参数兜底
        if not course_id:
            for key in ("classroom_id", "classroomId", "course_id", "courseId"):
                if key in query and query[key]:
                    course_id = query[key][0]
                    break
        return {
            "host": parsed.netloc,
            "course_id": course_id,
            "path_prefix": f"{parsed.scheme}://{parsed.netloc}",
        }

    def _url_in_course_scope(self, url: str) -> bool:
        if not self.course_scope:
            return True
        parsed = urlparse(url)
        if parsed.netloc != self.course_scope.get("host"):
            return False
        course_id = self.course_scope.get("course_id")
        if not course_id:
            return True
        segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
        return course_id in segments

    def _normalize_lesson_url(self, href: str):
        if not href:
            return None
        normalized = urljoin(self.page.url if self.page else "https://www.yuketang.cn", href)
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _remember_lesson_url(self, href: str):
        normalized = self._normalize_lesson_url(href)
        if normalized:
            self.visited_lesson_urls.add(normalized)

    def _clean_text(self, text: str) -> str:
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line in {"提交", "确认", "关闭", "跳过", "取消", "完成", "知道了"}:
                continue
            lines.append(line)
        return " ".join(lines).strip()

    def _clean_option_text(self, text: str) -> str:
        text = self._clean_text(text)
        if not text:
            return ""
        # 去掉选项前缀，避免 prompt 里出现 "A. A xxx" 干扰模型
        text = re.sub(r"^[A-H][\.、．:：\s]+", "", text).strip()
        return text
