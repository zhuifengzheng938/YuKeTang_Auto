"""Question popup handler for yuketang video-embedded questions.

Takes a QuestionSolver instance and handles the full lifecycle:
detect modal → extract stem+type+options → call solver → submit answer → detect feedback.
"""

import asyncio
import re
from playwright.async_api import Page

from selectors import (
    QUESTION_MODAL_SELECTORS, OPTION_SELECTORS, STEM_SELECTORS,
    SUBMIT_SELECTORS, SKIP_SELECTORS, QUESTION_FEEDBACK_SELECTORS,
)
from utils import clean_text, clean_option_text


class QuestionHandler:
    """Detect, extract, solve, and submit video-embedded question popups."""

    def __init__(self, page: Page, solver, answer_delay: int = 3):
        self.page = page
        self.solver = solver
        self.answer_delay = answer_delay
        self._attempts: dict[str, dict] = {}

    # -- main entry ------------------------------------------------------------

    async def check_and_handle(self) -> bool:
        """Scan all frames for a question modal; handle if found.  Returns True if handled."""
        for scope in [self.page, *self.page.frames]:
            modal = await self._find_visible_modal(scope)
            if modal:
                print("  检测到题目弹窗")
                await self._handle(modal)
                return True
        return False

    async def _handle(self, modal):
        await asyncio.sleep(1)

        stem = await self._extract_stem(modal)
        if not stem:
            print("  无法提取题目，尝试跳过")
            await self._try_skip(modal)
            return

        qkey = stem[:120]
        state = self._attempts.setdefault(qkey, {"attempts": 0, "failed_answers": set()})
        if state["attempts"] >= 3:
            print(f"  同一题已尝试 {state['attempts']} 次仍未通过，强制跳过以免卡死")
            await self._force_dismiss(modal)
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
                stem, options, q_type,
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

    # -- extraction ------------------------------------------------------------

    async def _extract_stem(self, modal) -> str:
        for sel in STEM_SELECTORS:
            el = await modal.query_selector(sel)
            if el:
                t = clean_text(await el.inner_text())
                if t:
                    return t
        return clean_text(await modal.inner_text())

    async def _extract_type_and_options(self, modal):
        modal_text = clean_text(await modal.inner_text())
        option_els = await self._find_option_elements(modal)
        options = []
        for el in option_els:
            text = clean_option_text(await el.inner_text())
            if text and text not in options:
                options.append(text)

        has_input = bool(await modal.query_selector(
            "input[type='text'], textarea, [contenteditable='true']"))
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
            if len(options) == 2 and any(
                word in joined for word in ["正确", "错误", "true", "false", "对", "错"]
            ):
                return "truefalse", options
            if "multiple" in lowered:
                return "multiple", options
            return "single", options
        if has_input:
            return "fillin", options
        return "unknown", options

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
                    text = clean_option_text(await el.inner_text())
                    if text:
                        filtered.append((el, text))
                except Exception:
                    continue
            if not filtered:
                continue
            if len(filtered) == 1 and self._count_option_markers(filtered[0][1]) >= 2:
                continue
            if len(filtered) >= 2:
                return [el for el, _ in filtered]
            if not best:
                best = [el for el, _ in filtered]
        return best

    # -- submission ------------------------------------------------------------

    async def _submit(self, modal, q_type: str, options: list, answer):
        option_els = await self._find_option_elements(modal)

        if q_type == "single":
            if not isinstance(answer, int) or not (0 <= answer < len(option_els)):
                await self._try_skip(modal)
                return "unknown"
            if not await self._click_option_by_index(modal, answer):
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
                await self._try_skip(modal)
                return "unknown"
            if not await self._click_option_by_index(modal, idx):
                await self._try_skip(modal)
                return "unknown"
            await asyncio.sleep(0.5)

        elif q_type == "multiple":
            if not isinstance(answer, list):
                await self._try_skip(modal)
                return "unknown"
            valid_indices = []
            for idx in answer:
                if isinstance(idx, int) and 0 <= idx < len(option_els) and idx not in valid_indices:
                    valid_indices.append(idx)
            for idx in answer:
                if isinstance(idx, int) and 0 <= idx < len(option_els) and idx not in valid_indices:
                    valid_indices.append(idx)
            if not valid_indices:
                await self._try_skip(modal)
                return "unknown"
            for idx in valid_indices:
                if not await self._click_option_by_index(modal, idx):
                    await self._try_skip(modal)
                    return "unknown"
                await asyncio.sleep(0.3)

        elif q_type == "fillin":
            if not isinstance(answer, str) or not answer.strip():
                await self._try_skip(modal)
                return "unknown"
            inp = await modal.query_selector(
                "input[type='text'], textarea, [contenteditable='true']")
            if not inp:
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
                        text = clean_text(await node.inner_text())
                        if any(kw in text for kw in ["题", "单选", "多选", "判断", "填空", "提交"]):
                            return node
                except Exception:
                    continue
        return None

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
            feedback = await self._detect_feedback(modal)
            if feedback == "wrong":
                return "retry"
            if feedback == "correct":
                return "submitted"
            try:
                if not await btn.is_visible():
                    return "submitted"
            except Exception:
                return "submitted"
        return "unknown"

    async def _detect_feedback(self, modal) -> str:
        texts = []
        for scope in [modal, self.page, *self.page.frames]:
            try:
                text = clean_text(await scope.inner_text())
                if text:
                    texts.append(text)
            except Exception:
                continue
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
                        t = clean_text(await node.inner_text())
                    except Exception:
                        continue
                    if any(marker in t for marker in wrong_markers):
                        return "wrong"
                    if any(marker in t for marker in correct_markers):
                        return "correct"
        return "unknown"

    async def _force_dismiss(self, modal):
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

    @staticmethod
    def _count_option_markers(text: str) -> int:
        return len(re.findall(r"(?:^|\s)[A-H](?:[\.、\．\:：\s])", " " + text))
