"""Video playback, monitoring, and completion detection for yuketang_bot."""

import asyncio
from playwright.async_api import Page

from utils import clean_text, lesson_text_is_finished


class VideoHandler:
    """Find video elements, ensure playback, monitor until completion.

    Integrates with QuestionHandler for embedded question popups,
    and ExerciseHandler for non-video lesson pages.
    """

    def __init__(self, page: Page, question_handler, exercise_handler=None,
                 monitor_interval: float = 1.0):
        self.page = page
        self.question_handler = question_handler
        self.exercise_handler = exercise_handler
        self.monitor_interval = monitor_interval

    # -- main entry ------------------------------------------------------------

    async def watch_page_video(self, remember_url_cb) -> bool:
        """Handle current lesson page. Returns True if content was processed.

        If no video is found, delegates to ExerciseHandler (if available).
        """
        remember_url_cb(self.page.url)

        if await self._page_shows_completion():
            print("  页面显示已完成，跳过当前课时")
            return False

        video = await self._find_video()
        if not video:
            # Check if this is an exercise page
            if self.exercise_handler and await self.exercise_handler.is_exercise_page():
                return await self.exercise_handler.handle(self.question_handler)
            print("  未找到视频，跳过")
            return False

        print("  使用默认 1x 倍速（稳定模式）")
        await self._override_visibility()
        await self._ensure_playing()
        await self._monitor_until_done()
        return True

    # -- video finding ---------------------------------------------------------

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

    # -- playback helpers ------------------------------------------------------

    async def _override_visibility(self):
        await self.page.evaluate("""
            Object.defineProperty(document, 'hidden',
                {get: () => false, configurable: true});
            Object.defineProperty(document, 'visibilityState',
                {get: () => 'visible', configurable: true});
            document.dispatchEvent(new Event('visibilitychange'));
        """)

    async def ensure_playing(self):
        """Public entry: make sure the video is playing (called after stall/question)."""
        await self._ensure_playing()

    async def _ensure_playing(self):
        # 1) Dismiss blocking layers
        await self._dismiss_blocking_layers()

        # 2) JS force-play + pause override
        force_play_js = """
            () => {
                const seen = new Set();
                function collect(root) {
                    if (!root || seen.has(root)) return;
                    seen.add(root);
                    try {
                        root.querySelectorAll('video').forEach(v => {
                            if (v.paused) { v.play().catch(() => {}); }
                            if (!v.__yuketang_override_pause) {
                                const origPause = v.pause.bind(v);
                                let suppressCount = 0;
                                v.pause = function() {
                                    suppressCount++;
                                    if (suppressCount <= 3) origPause();
                                };
                                v.addEventListener('pause', e => {
                                    if (v.currentTime > 0 && v.currentTime < v.duration - 1) {
                                        v.play().catch(() => {});
                                    }
                                }, true);
                                v.__yuketang_override_pause = true;
                            }
                        });
                        root.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) collect(el.shadowRoot);
                        });
                    } catch (_) {}
                }
                collect(document);
            }
        """
        await self.page.evaluate(force_play_js)
        for frame in self.page.frames:
            try:
                await frame.evaluate(force_play_js)
            except Exception:
                pass

        # 3) Click visible play buttons
        play_selectors = [
            "button.vjs-big-play-button", ".vjs-big-play-button",
            "button[class*='play']", "[class*='play-btn']", "[class*='play-button']",
            "[class*='start-play']", "[role='button'][class*='play']",
            "text=播放", "text=▶",
            "[class*='start_play']", "[class*='big-play']",
            "[class*='xt_video'] [class*='play']",
            "[class*='xt-player'] [class*='play']",
            "xt-playbutton",
        ]
        clicked_any = False
        for scope in [self.page, *self.page.frames]:
            for sel in play_selectors:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        clicked_any = True
                        await asyncio.sleep(0.3)
                except Exception:
                    continue

        # 4) Fallback: click video + Space key
        try:
            video = await self._find_video()
            if video:
                await video.click()
                await asyncio.sleep(0.2)
        except Exception:
            pass
        if not clicked_any:
            try:
                await self.page.keyboard.press("Space")
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # 5) Extra play ping after delay
        await asyncio.sleep(0.3)
        await self.page.evaluate("""
            () => { document.querySelectorAll('video').forEach(v => {
                if (v.paused) v.play().catch(() => {});
            }); }
        """)

    async def _dismiss_blocking_layers(self):
        dismiss_texts = ["知道了", "关闭", "确定", "确认", "好的", "开始学习", "继续学习", "进入学习"]
        for scope in [self.page, *self.page.frames]:
            for sel in [
                ".el-dialog", ".ant-modal", ".ant-modal-content",
                "[class*='overlay']", "[class*='mask']", "[class*='modal']",
                "[class*='dialog']", "[class*='popup']",
            ]:
                try:
                    nodes = await scope.query_selector_all(sel)
                except Exception:
                    continue
                for node in nodes:
                    try:
                        if not await node.is_visible():
                            continue
                        text = await node.inner_text()
                        if any(t in text for t in dismiss_texts):
                            for btn_sel in [
                                "button", "a", "[role='button']",
                                ".el-dialog__close", ".ant-modal-close",
                                ".close", "[class*='close']",
                            ]:
                                btn = await node.query_selector(btn_sel)
                                if btn and await btn.is_visible():
                                    await btn.click()
                                    await asyncio.sleep(0.3)
                                    break
                    except Exception:
                        continue

    # -- monitoring loop -------------------------------------------------------

    async def _monitor_until_done(self):
        print("  监控视频播放中…")
        stall_count = 0
        total_stall_recoveries = 0
        max_stall_recoveries = 30
        last_time = -1.0
        missing_video_count = 0
        last_known_duration = 0.0
        last_known_current_time = 0.0
        max_seen_progress = 0.0

        while True:
            if await self._page_shows_completion():
                video_state = await self._get_video_state()
                if video_state["missing"] or video_state["done"]:
                    print("  页面显示已完成且视频确认结束，结束当前课时")
                    await asyncio.sleep(2.0)
                    return
                dur = video_state.get("duration") or 0
                cur = video_state.get("current_time") or 0
                if dur > 0 and cur < dur * 0.9 and max_seen_progress < 0.9:
                    print("  页面文字疑似误判已完成（视频进度尚早），继续监控")
                else:
                    print("  页面显示已完成，结束当前课时")
                    await asyncio.sleep(2.0)
                    return

            if await self.question_handler.check_and_handle():
                await self._ensure_playing()
                stall_count = 0
                continue

            video_state = await self._get_video_state()
            if not video_state["missing"]:
                last_known_duration = video_state.get("duration") or 0
                last_known_current_time = video_state.get("current_time") or 0
                dur = video_state.get("duration") or 0
                cur = video_state.get("current_time") or 0
                if dur > 0:
                    progress = cur / dur
                    if progress > max_seen_progress:
                        max_seen_progress = progress

            if video_state["missing"]:
                missing_video_count += 1
                if await self._page_shows_completion():
                    if (last_known_duration > 0 and last_known_current_time < last_known_duration * 0.6
                            and max_seen_progress < 0.6):
                        print("  视频消失但进度尚早，页面文字可能误判已完成，继续等待")
                    else:
                        print("  页面显示已完成且视频已消失，结束当前课时")
                        await asyncio.sleep(2.0)
                        return
                if missing_video_count >= 5:
                    print("  视频元素暂时消失，结束当前课时")
                    return
                await asyncio.sleep(self.monitor_interval)
                continue

            missing_video_count = 0
            if video_state["done"]:
                print(f"  视频播放完成！{self._format_video_state(video_state)}")
                await asyncio.sleep(2.0)
                return

            cur = video_state["current_time"]
            if abs(cur - last_time) < 0.1:
                stall_count += 1
                if stall_count >= 5:
                    total_stall_recoveries += 1
                    if total_stall_recoveries >= max_stall_recoveries:
                        print(f"  视频已停滞 {total_stall_recoveries} 次无法恢复，跳过当前课时")
                        return
                    print(f"  检测到播放停滞，尝试恢复{self._format_video_state(video_state)}")
                    if total_stall_recoveries <= 2:
                        debug = await self._debug_video_count()
                        if debug:
                            print(f"  页面上视频元素信息:{debug}")
                    await self._ensure_playing()
                    stall_count = 0
            else:
                stall_count = 0
            last_time = cur

            await asyncio.sleep(self.monitor_interval)

    # -- video state querying --------------------------------------------------

    async def _get_video_state(self):
        script = """
            () => {
                const allVideos = [];
                const seen = new Set();
                function collect(root) {
                    if (!root || seen.has(root)) return;
                    seen.add(root);
                    try {
                        root.querySelectorAll('video').forEach(v => allVideos.push(v));
                        root.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) collect(el.shadowRoot);
                        });
                    } catch (_) {}
                }
                collect(document);
                if (!allVideos.length) {
                    return {missing: true, done: false, current_time: 0};
                }
                const candidates = allVideos.map((v, index) => {
                    const rect = typeof v.getBoundingClientRect === 'function'
                        ? v.getBoundingClientRect() : {width: 0, height: 0};
                    const style = window.getComputedStyle ? window.getComputedStyle(v) : null;
                    const visible = !!(rect.width > 0 && rect.height > 0 && style &&
                        style.visibility !== 'hidden' && style.display !== 'none');
                    const duration = Number.isFinite(v.duration) ? v.duration : 0;
                    const currentTime = Number.isFinite(v.currentTime) ? v.currentTime : 0;
                    const score = (visible ? 1000 : 0) + Math.min(duration, 36000) +
                        Math.min(currentTime, 36000) + (!v.paused ? 500 : 0) +
                        (v.readyState || 0) * 20 + (v.ended ? -2000 : 0);
                    return {index, visible, paused: !!v.paused, ended: !!v.ended,
                            current_time: currentTime, duration, ready_state: v.readyState || 0,
                            playback_rate: v.playbackRate, score};
                });
                candidates.sort((a, b) => b.score - a.score);
                const v = candidates[0];
                return {
                    missing: false,
                    source: `video[${v.index}]`,
                    done: !!(v.ended || (v.duration > 0 &&
                        v.current_time >= Math.max(v.duration - 0.5, v.duration * 0.995))),
                    current_time: v.current_time, duration: v.duration,
                    paused: v.paused, ready_state: v.ready_state, ended: v.ended,
                    playback_rate: v.playback_rate, candidates,
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
        return {"missing": True, "done": False, "current_time": 0,
                "duration": 0, "paused": True, "ready_state": 0,
                "ended": False, "source": "none"}

    async def _debug_video_count(self) -> str:
        script = """
            () => {
                const seen = new Set(); let count = 0; const infos = [];
                function collect(root) {
                    if (!root || seen.has(root)) return;
                    seen.add(root);
                    try {
                        root.querySelectorAll('video').forEach(v => {
                            const r = v.getBoundingClientRect();
                            const s = v.currentSrc || '';
                            const src = s.includes('/') ? '...' + s.slice(-60) : s;
                            infos.push('#' + count + ' w=' + Math.round(r.width) + ' h=' +
                                Math.round(r.height) + ' paused=' + v.paused + ' cur=' +
                                (v.currentTime||0).toFixed(1) + ' dur=' + (v.duration||0).toFixed(0) +
                                ' rs=' + (v.readyState||0) + ' ended=' + v.ended +
                                ' src=' + src.slice(0,50));
                            count++;
                        });
                        root.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) collect(el.shadowRoot);
                        });
                    } catch (_) {}
                }
                collect(document);
                return infos.join('\\n');
            }
        """
        try:
            result = await self.page.evaluate(script)
            return "\n" + result if result else ""
        except Exception:
            return ""

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
                            text = clean_text(await node.inner_text())
                            if lesson_text_is_finished(text):
                                return True
                    except Exception:
                        continue
        try:
            body_text = clean_text(await self.page.inner_text("body"))
            return lesson_text_is_finished(body_text)
        except Exception:
            return False

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

    # -- next-lesson navigation (fallback when catalog unreachable) -------------

    async def watch_next_lessons(self, advance_callback, catalog_url: str | None,
                                 visited_urls: set, course_scope: dict):
        """Fallback loop: keep advancing to next lesson in the same course."""
        while True:
            next_url = await advance_callback(catalog_url, visited_urls, course_scope)
            if not next_url:
                print("同一课程下未找到下一个可播放视频，结束")
                return
            print(f"自动切换到下一节: {next_url}")
            visited_urls.add(next_url)
            await self.watch_page_video(lambda u: visited_urls.add(u))
