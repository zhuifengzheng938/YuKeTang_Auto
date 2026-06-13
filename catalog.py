"""Catalog navigation for yuketang_bot.

Handles catalog page enumeration, scrolling, lesson picking, expanding
collapsed sections, and navigating back to the catalog after watching a video.
"""

import asyncio
from playwright.async_api import Page

from selectors import (
    START_STUDY_SELECTORS, LESSON_ENTRY_SELECTORS, CATALOG_TOGGLE_SELECTORS,
    EXPAND_TOGGLE_SELECTORS, BACK_TO_CATALOG_SELECTORS, CATALOG_LESSON_SELECTOR,
    NEXT_LESSON_SELECTORS,
)
from utils import (
    normalize_lesson_url, url_in_course_scope, lesson_key,
    lesson_text_is_finished, is_summary_node, clean_text,
)


class CatalogNavigator:
    """Navigates yuketang course catalog: scan, expand, pick unfinished lessons."""

    def __init__(self, page: Page, goto_cb, go_back_cb, wait_ready_cb,
                 visited_urls: set, visited_keys: set):
        self.page = page
        self._goto = goto_cb          # async (url, timeout=...)
        self._go_back = go_back_cb    # async (timeout=...)
        self._wait_ready = wait_ready_cb  # async (timeout=...)
        self.visited_urls = visited_urls
        self.visited_keys = visited_keys
        self.catalog_url: str | None = None
        self.course_scope: dict | None = None

    # -- helpers ---------------------------------------------------------------

    def _remember_url(self, href: str):
        n = normalize_lesson_url(href)
        if n:
            self.visited_urls.add(n)

    def _mark_visited(self, lesson: dict):
        key = lesson.get("key")
        if key:
            self.visited_keys.add(key)
        href = lesson.get("href")
        if href:
            self.visited_urls.add(href)

    async def _is_direct_video_page(self) -> bool:
        url = self.page.url
        if any(kw in url for kw in ["video-student", "/lesson/", "/learn/"]):
            return True
        try:
            return await self.page.query_selector("video") is not None
        except Exception:
            return False

    # -- open / expand ---------------------------------------------------------

    async def open_study_entry_if_needed(self):
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

    async def expand_catalog_if_needed(self):
        for sel in CATALOG_TOGGLE_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                continue
        await self._expand_all_sections()

    async def _expand_all_sections(self):
        for _ in range(8):
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
                            text = clean_text(await node.inner_text())
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

    # -- return to catalog -----------------------------------------------------

    async def go_to_catalog_page(self) -> bool:
        # 1) direct URL
        if self.catalog_url:
            try:
                await self._goto(self.catalog_url)
                await self._wait_ready()
                await asyncio.sleep(2)
                if not await self._is_direct_video_page():
                    await self.expand_catalog_if_needed()
                    return True
            except Exception:
                pass
        # 2) click "return" button
        if await self._click_return_button():
            if not self.catalog_url and not await self._is_direct_video_page():
                self.catalog_url = normalize_lesson_url(self.page.url)
            await self.expand_catalog_if_needed()
            return True
        # 3) browser back
        try:
            await self._go_back()
            await self._wait_ready()
            await asyncio.sleep(2)
            if not await self._is_direct_video_page():
                if not self.catalog_url:
                    self.catalog_url = normalize_lesson_url(self.page.url)
                await self.expand_catalog_if_needed()
                return True
        except Exception:
            pass
        return False

    async def _click_return_button(self) -> bool:
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

    # -- scrolling -------------------------------------------------------------

    async def _scroll_to_top(self):
        try:
            await self.page.evaluate("""
                () => {
                    document.querySelectorAll(
                        '.viewContainer, .logs-list, [class*="lesson"], [class*="catalog"], [class*="leaf"]'
                    ).forEach(c => { c.scrollTop = 0; });
                    window.scrollTo(0, 0);
                }
            """)
            await asyncio.sleep(0.8)
        except Exception:
            pass

    async def _scroll_page_down(self) -> bool:
        try:
            return await self.page.evaluate("""
                () => {
                    const containers = Array.from(document.querySelectorAll(
                        '.viewContainer, .logs-list, [class*="lesson"], [class*="catalog"], [class*="leaf"]'
                    )).filter(c => c.scrollHeight > c.clientHeight + 5);
                    const target = containers.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] ||
                                   document.scrollingElement;
                    if (!target) return false;
                    const before = target.scrollTop;
                    target.scrollTop = before + Math.max(300, Math.floor(target.clientHeight * 0.8));
                    if (target === document.scrollingElement) window.scrollTo(0, target.scrollTop);
                    return target.scrollTop !== before;
                }
            """)
        except Exception:
            return False
        finally:
            await asyncio.sleep(0.8)

    async def _scroll_signature(self) -> str:
        try:
            return await self.page.evaluate("""
                () => {
                    const containers = Array.from(document.querySelectorAll(
                        '.viewContainer, .logs-list, [class*="lesson"], [class*="catalog"], [class*="leaf"]'
                    )).filter(c => c.scrollHeight > c.clientHeight + 5);
                    const target = containers.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] ||
                                   document.scrollingElement;
                    if (!target) return 'none';
                    return `${Math.round(target.scrollTop)}:${Math.round(target.scrollHeight)}:${Math.round(target.clientHeight)}`;
                }
            """)
        except Exception:
            return "unknown"

    # -- lesson picking --------------------------------------------------------

    async def pick_next_unfinished_lesson(self) -> dict | None:
        await self._scroll_to_top()
        seen_pages = set()
        for _ in range(80):
            candidates = await self._collect_visible_candidates()
            if candidates:
                candidates.sort(key=lambda c: (round(c["top"] / 5), c["left"]))
                return candidates[0]
            pos = await self._scroll_signature()
            if pos in seen_pages:
                break
            seen_pages.add(pos)
            moved = await self._scroll_page_down()
            if not moved:
                break
        return None

    async def _collect_visible_candidates(self) -> list:
        candidates = []
        total_found = 0
        filtered_summary = 0
        filtered_finished = 0
        filtered_visited = 0
        for scope in [self.page, *self.page.frames]:
            try:
                elements = await scope.query_selector_all(CATALOG_LESSON_SELECTOR)
            except Exception:
                continue
            for el in elements:
                try:
                    if not await el.is_visible():
                        continue
                    total_found += 1
                    href = normalize_lesson_url(await el.get_attribute("href"))
                    text = clean_text(await el.inner_text())
                    classes = ((await el.get_attribute("class")) or "").lower()
                    if href and not url_in_course_scope(href, self.course_scope):
                        continue
                    if "disabled" in classes or "lock" in classes:
                        continue
                    if is_summary_node(text, href):
                        filtered_summary += 1
                        continue
                    if lesson_text_is_finished(text):
                        filtered_finished += 1
                        continue
                    key = lesson_key(href, text)
                    if not key or key in self.visited_keys:
                        filtered_visited += 1
                        continue
                    if href and href in self.visited_urls:
                        filtered_visited += 1
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
        if total_found > 0:
            print(f"  目录扫描: 可见{total_found}个 → "
                  f"汇总{filtered_summary} 已完成{filtered_finished} "
                  f"已访问{filtered_visited} 候选{len(candidates)}")
        return candidates

    async def open_lesson(self, lesson: dict) -> bool:
        href = lesson.get("href")
        if href:
            return await self._open_url(href)
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

    async def _open_url(self, href: str) -> bool:
        if not href:
            return False
        try:
            await self._goto(href)
            await self._wait_ready()
            await asyncio.sleep(2)
            return True
        except Exception:
            return False

    # -- fallback: advance to next lesson in same course -----------------------

    async def find_next_lesson(self, catalog_url: str | None,
                               visited_urls: set, course_scope: dict) -> str | None:
        """Fallback: advance to next lesson without returning to catalog."""
        await self.expand_catalog_if_needed()

        next_url = await self._click_explicit_next()
        if next_url:
            return next_url

        next_url = await self._find_next_after_current(visited_urls, course_scope)
        if next_url and await self._open_url(next_url):
            return normalize_lesson_url(self.page.url) or next_url

        next_url = await self._click_next_item_after_current(visited_urls)
        if next_url:
            return next_url

        if await self._click_return_button():
            await self.expand_catalog_if_needed()
            next_url = await self._find_next_after_current(visited_urls, course_scope)
            if next_url and await self._open_url(next_url):
                return normalize_lesson_url(self.page.url) or next_url
            next_url = await self._click_next_item_after_current(visited_urls)
            if next_url:
                return next_url

        return await self._scan_all_candidates(visited_urls, course_scope)

    async def _click_explicit_next(self) -> str | None:
        for sel in NEXT_LESSON_SELECTORS:
            try:
                btn = await self.page.query_selector(sel)
                if not btn or not await btn.is_visible():
                    continue
                href = await btn.get_attribute("href")
                if href:
                    n = normalize_lesson_url(href)
                    if n and await self._open_url(n):
                        return normalize_lesson_url(self.page.url) or n
                    continue
                await btn.click()
                await self._wait_ready()
                await asyncio.sleep(2)
                current = normalize_lesson_url(self.page.url)
                if current and current not in self.visited_urls:
                    return current
            except Exception:
                continue
        return None

    async def _find_next_after_current(self, visited_urls: set,
                                       course_scope: dict) -> str | None:
        current = normalize_lesson_url(self.page.url)
        if not current:
            return None
        js = """
            els => els.map(el => ({
                href: el.href,
                text: (el.innerText || '').trim(),
                classes: el.className || '',
                ariaCurrent: el.getAttribute('aria-current') || '',
            }))
        """
        selector = "a[href*='video-student'], a[href*='leafId'], a[href*='lesson'], a[href*='learn']"
        candidates = []
        for scope in [self.page, *self.page.frames]:
            try:
                items = await scope.eval_on_selector_all(selector, js)
                if items:
                    candidates.extend(items)
            except Exception:
                continue
        seen_current = False
        for item in candidates:
            href = normalize_lesson_url(item.get("href"))
            if not href or not url_in_course_scope(href, course_scope):
                continue
            text = clean_text(item.get("text") or "")
            classes = (item.get("classes") or "").lower()
            aria_current = (item.get("ariaCurrent") or "").lower()
            is_current = (href == current or aria_current == "page"
                          or "current" in classes or "active" in classes)
            if is_current:
                seen_current = True
                continue
            if not seen_current:
                continue
            if href in visited_urls:
                continue
            if any(flag in text for flag in ["已完成", "100%", "完成"]):
                continue
            return href
        return None

    async def _click_next_item_after_current(self, visited_urls: set) -> str | None:
        current = normalize_lesson_url(self.page.url)
        if not current:
            return None
        selector = ", ".join(LESSON_ENTRY_SELECTORS)
        items = await self.page.query_selector_all(selector)
        seen_current = False
        for item in items:
            try:
                if not await item.is_visible():
                    continue
                href = normalize_lesson_url(await item.get_attribute("href"))
                text = clean_text(await item.inner_text())
                classes = ((await item.get_attribute("class")) or "").lower()
                is_current = (href == current or "current" in classes or "active" in classes)
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
                next_url = normalize_lesson_url(self.page.url)
                if next_url and next_url not in visited_urls:
                    return next_url
            except Exception:
                continue
        return None

    async def _scan_all_candidates(self, visited_urls: set,
                                    course_scope: dict) -> str | None:
        js = """
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
                items = await scope.eval_on_selector_all(selector, js)
                if items:
                    candidates.extend(items)
            except Exception:
                continue
        for item in candidates:
            href = normalize_lesson_url(item.get("href"))
            if not href or not url_in_course_scope(href, course_scope):
                continue
            if href in visited_urls:
                continue
            text = clean_text(item.get("text") or "")
            classes = (item.get("classes") or "").lower()
            aria_current = (item.get("ariaCurrent") or "").lower()
            aria_disabled = (item.get("ariaDisabled") or "").lower()
            if aria_current == "page" or "current" in classes or "active" in classes:
                continue
            if aria_disabled == "true" or "disabled" in classes or "lock" in classes:
                continue
            if any(flag in text for flag in ["已完成", "100%", "完成"]):
                continue
            if await self._open_url(href):
                return normalize_lesson_url(self.page.url) or href
        return None
