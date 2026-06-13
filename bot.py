"""YuketangBot — thin orchestrator for automated yuketang course watching.

Wires together BrowserSession, QuestionHandler, ExerciseHandler,
CatalogNavigator, and VideoHandler.
"""

import asyncio
from solver import QuestionSolver
from browser import BrowserSession
from questions import QuestionHandler
from exercises import ExerciseHandler
from catalog import CatalogNavigator
from video import VideoHandler
from utils import normalize_lesson_url, extract_course_scope


class YuketangBot:
    """Automated yuketang course watcher with AI-powered question answering."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        web_search: bool = True,
        speed: float = 2.0,          # reserved, not currently used
        answer_delay: int = 3,
        quiet: bool = False,
    ):
        self.solver = QuestionSolver(api_key, base_url, model, web_search=web_search)
        self.quiet = quiet
        self.answer_delay = answer_delay
        self.session = BrowserSession(quiet=quiet)

        # Created after session starts (need page)
        self._question: QuestionHandler | None = None
        self._exercise: ExerciseHandler | None = None
        self._catalog: CatalogNavigator | None = None
        self._video: VideoHandler | None = None

        # Mutable state shared with catalog
        self.visited_urls: set = set()
        self.visited_keys: set = set()

    # -- async context manager -------------------------------------------------

    async def __aenter__(self):
        await self.session.start()
        page = self.session.page

        self._question = QuestionHandler(page, self.solver, self.answer_delay)
        self._exercise = ExerciseHandler(page)
        self._catalog = CatalogNavigator(
            page,
            goto_cb=self.session.goto,
            go_back_cb=self.session.go_back,
            wait_ready_cb=self.session.wait_ready,
            visited_urls=self.visited_urls,
            visited_keys=self.visited_keys,
        )
        self._video = VideoHandler(
            page,
            self._question,
            exercise_handler=self._exercise,
            monitor_interval=self.session.monitor_interval,
        )
        return self

    async def __aexit__(self, *_):
        await self.session.stop()

    # -- public API ------------------------------------------------------------

    async def login(self, timeout: int = 120):
        await self.session.login(timeout=timeout)

    async def watch_course(self, course_url: str):
        """Main entry: watch all unfinished lessons in a course."""
        self._catalog.course_scope = extract_course_scope(course_url)
        self.visited_urls.clear()
        self.visited_keys.clear()
        self._catalog.catalog_url = None

        await self.session.goto(course_url)
        await self.session.wait_ready()
        await asyncio.sleep(2)

        # Entry point: could be a single video page or a catalog
        if await self._catalog._is_direct_video_page():
            print("入口是视频学习页，先播放当前视频，随后返回目录继续")
            self._catalog._remember_url(self.session.page.url)
            await self._video.watch_page_video(self._remember_current_url)
            if not await self._catalog.go_to_catalog_page():
                print("无法返回课程目录，改用视频页内兜底查找下一节")
                await self._fallback_next_lessons()
                return
        else:
            self._catalog.catalog_url = normalize_lesson_url(self.session.page.url)
            await self._catalog.open_study_entry_if_needed()
            if await self._catalog._is_direct_video_page():
                self._catalog._remember_url(self.session.page.url)
                await self._video.watch_page_video(self._remember_current_url)
                if not await self._catalog.go_to_catalog_page():
                    print("无法返回课程目录，改用视频页内兜底查找下一节")
                    await self._fallback_next_lessons()
                    return

        # Catalog-driven loop
        if not self._catalog.catalog_url:
            self._catalog.catalog_url = normalize_lesson_url(self.session.page.url)
        await self._run_catalog_loop()

    # -- internal --------------------------------------------------------------

    def _remember_current_url(self, url: str):
        n = normalize_lesson_url(url)
        if n:
            self.visited_urls.add(n)

    async def _run_catalog_loop(self):
        print("进入目录驱动模式：从课程目录页依次处理未完成视频")
        empty_rounds = 0
        while True:
            await self._catalog.expand_catalog_if_needed()
            lesson = await self._catalog.pick_next_unfinished_lesson()
            if not lesson:
                empty_rounds += 1
                if empty_rounds >= 2:
                    print("课程目录中已无未完成的可播放视频，结束")
                    return
                await asyncio.sleep(2)
                continue
            empty_rounds = 0

            label = (lesson.get("text") or lesson.get("href") or "下一课时")[:60]
            print(f"打开课时: {label}")
            self._catalog._mark_visited(lesson)
            if not await self._catalog.open_lesson(lesson):
                print("  打开该课时失败，跳过")
                continue

            self._catalog._remember_url(self.session.page.url)
            await self._video.watch_page_video(self._remember_current_url)

            if not await self._catalog.go_to_catalog_page():
                print("  播放后无法回到目录页，改用视频页内兜底继续")
                await self._fallback_next_lessons()
                return

    async def _fallback_next_lessons(self):
        await self._video.watch_next_lessons(
            self._catalog.find_next_lesson,
            self._catalog.catalog_url,
            self.visited_urls,
            self._catalog.course_scope,
        )
