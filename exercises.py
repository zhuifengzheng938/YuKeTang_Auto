"""Exercise page handler for yuketang_bot.

Detects standalone exercise/test pages (no video) and automatically
answers questions using the AI-powered QuestionSolver.

Supports single-page quizzes, per-question navigation, and multi-page exams.
"""

import asyncio
import base64
import re

from playwright.async_api import Page

from ocr import ocr_from_base64
from selectors import (
    EXERCISE_QUESTION_BLOCK_SELECTORS, EXERCISE_OPTION_SELECTORS,
    EXERCISE_SUBMIT_SELECTORS, EXERCISE_NEXT_PAGE_SELECTORS,
    EXERCISE_PREV_PAGE_SELECTORS, EXERCISE_CONFIRM_SELECTORS,
    STEM_SELECTORS,
)
from utils import clean_text, clean_option_text


class ExerciseHandler:
    """Detect and handle standalone exercise/test pages (no video).

    Reuses QuestionSolver from QuestionHandler for AI-powered answering.
    Handles three page modes:
      - single-page: all questions on one page, one submit button
      - per-question: one question per page, with next-prev navigation
      - multi-page: multiple pages of questions, paginated
    """

    EXERCISE_MARKERS = [
        "答题", "习题", "测验", "考试", "练习", "试卷",
        "单选题", "多选题", "判断题", "填空题",
        "提交试卷", "交卷", "开始答题",
    ]

    def __init__(self, page: Page):
        self.page = page

    # -- detection ---------------------------------------------------------------

    async def is_exercise_page(self) -> bool:
        """Check if current page is an exercise/test page (no video, has question markers)."""
        try:
            text = await self.page.inner_text("body")
        except Exception:
            return False
        hits = sum(1 for m in self.EXERCISE_MARKERS if m in text)
        return hits >= 2

    # -- main entry --------------------------------------------------------------

    async def handle(self, question_handler) -> bool:
        """Handle exercises on the current page.

        Args:
            question_handler: QuestionHandler instance for solver reuse.

        Returns:
            True if exercises were handled, False to skip.
        """
        solver = question_handler.solver
        answer_delay = getattr(question_handler, "answer_delay", 3)

        print("  \U0001F50D 检测到习题/测验页面，开始自动作答…")

        failed_answers: dict[str, dict] = {}
        processed_count = 0
        seen_stems: set = set()   # dedup by stem to avoid answering same question twice
        empty_rounds = 0

        try:
            while True:
                await asyncio.sleep(1.5)

                # Detect navigation mode: per-question ("下一题") vs page-based ("下一页")
                has_next_question = await self._has_next_question()

                blocks = await self._find_question_blocks()
                if not blocks:
                    empty_rounds += 1
                    if empty_rounds >= 3:
                        print("  连续多次未找到题目块，退出作答")
                        break
                    # Try any navigation to advance
                    if has_next_question:
                        if not await self._go_next_question():
                            break
                        continue
                    if await self._has_next_page():
                        await self._go_next_page()
                        continue
                    print("  未找到题目块且无翻页按钮，可能已完成全部习题")
                    break

                print(f"  当前页面发现 {len(blocks)} 个题目块（逐题模式: {'是' if has_next_question else '否'}）")

                page_answered = 0
                for i, block in enumerate(blocks):
                    q_info = await self._extract_question(block)
                    if not q_info or not q_info["stem"]:
                        continue

                    # Dedup by stem (first 40 chars + last 40 chars) — robust to OCR variations
                    stem_sig = q_info["stem"][:40] + q_info["stem"][-40:]
                    if stem_sig in seen_stems:
                        continue
                    seen_stems.add(stem_sig)

                    qkey = q_info["stem"][:40]  # shorter key for retry state
                    state = failed_answers.setdefault(
                        qkey, {"attempts": 0, "failed": set()})

                    stem_preview = q_info["stem"][:200]
                    print(f"    题{processed_count + 1}: {stem_preview}"
                          f"{'…' if len(q_info['stem']) > 200 else ''}")
                    print(f"    ({q_info['q_type']}, {len(q_info['options'])}个选项)")

                    success = await self._answer_question(
                        block, q_info, solver, answer_delay, state)
                    if success:
                        processed_count += 1
                        page_answered += 1
                        empty_rounds = 0

                # After answering, check if page auto-advanced (submit → next question)
                already_advanced = False
                if page_answered > 0:
                    await asyncio.sleep(1)
                    new_blocks = await self._find_question_blocks()
                    if new_blocks:
                        new_q = await self._extract_question(new_blocks[0])
                        if new_q and new_q["stem"]:
                            new_sig = new_q["stem"][:80]
                            if new_sig not in seen_stems:
                                already_advanced = True
                                print("    提交后已自动跳转")

                # Navigation: only click next if page didn't auto-advance
                if already_advanced:
                    continue
                elif page_answered > 0:
                    # Answered something this round, try advancing
                    if has_next_question and await self._has_next_question():
                        await self._go_next_question()
                        await asyncio.sleep(2)
                        continue
                    elif await self._has_next_page():
                        await self._go_next_page()
                        await asyncio.sleep(2)
                        continue
                    else:
                        break
                else:
                    # Nothing new answered — maybe last page or stuck
                    empty_rounds += 1
                    if empty_rounds >= 2:
                        print("  连续两轮无新题作答，退出")
                        break
                    # Try forcing advance
                    if has_next_question and await self._has_next_question():
                        await self._go_next_question()
                        await asyncio.sleep(1.5)
                        continue
                    elif await self._has_next_page():
                        await self._go_next_page()
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        break

            # Submit the entire exam
            if await self._click_exercise_submit():
                print("  ✅ 习题提交成功")
            else:
                print("  未找到提交按钮（可能已逐题提交）")
            await self._handle_confirm_dialog()

        except Exception as exc:
            print(f"  习题处理异常：{exc}，跳过当前页面")
            return False

        print(f"  习题处理完成：作答 {processed_count} 题")
        return processed_count > 0

    # -- question block discovery ------------------------------------------------

    async def _find_question_blocks(self) -> list:
        """Find visible question blocks on the current page across all frames.

        Deduplicates nested matches (prefer outer containers).
        """
        found = []
        seen_ids = set()

        for scope in [self.page, *self.page.frames]:
            for sel in EXERCISE_QUESTION_BLOCK_SELECTORS:
                try:
                    elements = await scope.query_selector_all(sel)
                except Exception:
                    continue
                for el in elements:
                    try:
                        if not await el.is_visible():
                            continue
                        try:
                            el_id = await el.evaluate("el => el")
                        except Exception:
                            continue
                        if el_id in seen_ids:
                            continue
                        seen_ids.add(el_id)

                        # Quick sanity: does it contain option-like elements or true/false text?
                        has_options = False
                        for opt_sel in EXERCISE_OPTION_SELECTORS:
                            try:
                                child = await el.query_selector(opt_sel)
                                if child:
                                    has_options = True
                                    break
                            except Exception:
                                continue
                        if not has_options:
                            # True/false blocks may not have radio/checkbox selectors
                            try:
                                text = await el.inner_text()
                                if any(kw in text for kw in ["正确", "错误", "对", "错", "判断", "单选", "多选"]):
                                    has_options = True
                            except Exception:
                                pass
                        if has_options:
                            found.append(el)
                    except Exception:
                        continue

            if found:
                break

        # Dedup: remove blocks that are ancestors of other blocks
        found = await self._remove_ancestor_blocks(found)

        # Fallback: if no dedicated blocks found, try finding radio groups
        if not found:
            found = await self._fallback_find_blocks_by_inputs()

        return found

    async def _remove_ancestor_blocks(self, blocks: list) -> list:
        """Remove blocks that contain other blocks (keep outermost)."""
        if len(blocks) <= 1:
            return blocks
        filtered = []
        for el in blocks:
            is_contained = False
            try:
                for other in blocks:
                    if other is el:
                        continue
                    if await el.evaluate(
                        "child => parent => parent.contains(child)",
                        other,
                    ):
                        is_contained = True
                        break
            except Exception:
                pass
            if not is_contained:
                filtered.append(el)
        return filtered

    async def _fallback_find_blocks_by_inputs(self) -> list:
        """Fallback: find question containers by radio/checkbox input groups."""
        found = []
        seen_ids = set()

        # Collect all radio/checkbox groups
        radio_groups: dict[str, list] = {}
        for scope in [self.page, *self.page.frames]:
            for sel in ["input[type='radio']", "input[type='checkbox']"]:
                try:
                    inputs = await scope.query_selector_all(sel)
                except Exception:
                    continue
                for inp in inputs:
                    try:
                        if not await inp.is_visible():
                            continue
                        name = await inp.get_attribute("name") or ""
                        radio_groups.setdefault(name or f"__anon_{id(inp)}", []).append(inp)
                    except Exception:
                        continue

        if not radio_groups:
            return []

        for _name, inputs in radio_groups.items():
            if not inputs:
                continue
            try:
                container = await inputs[0].evaluate_handle(
                    """el => {
                        let p = el.parentElement;
                        for (let i = 0; i < 6 && p; i++) {
                            const text = (p.innerText || '').trim();
                            // Look for a container with substantial text
                            // but not the entire body
                            if (text.length > 40 && p !== document.body
                                && p.children.length >= 2) {
                                return p;
                            }
                            p = p.parentElement;
                        }
                        return el.closest('form, fieldset, [class*="question"], [class*="problem"]')
                            || el.parentElement;
                    }"""
                )
                if container:
                    el = container.as_element()
                    try:
                        el_id = await el.evaluate("el => el")
                    except Exception:
                        continue
                    if el_id not in seen_ids:
                        seen_ids.add(el_id)
                        found.append(el)
            except Exception:
                continue

        # Dedup fallback results too
        return await self._remove_ancestor_blocks(found)

    # -- question extraction -----------------------------------------------------

    async def _extract_question(self, block) -> dict | None:
        """Extract stem, type, options, and option elements from a question block.

        Uses OCR on a screenshot to get real text (bypasses font obfuscation).
        Falls back to DOM text if OCR fails.

        Returns dict with keys: stem, q_type, options, option_els, input_el.
        """
        dom_stem = await self._extract_stem(block)

        # OCR the screenshot to get real text (anti-font-obfuscation)
        screenshot_b64 = await self._screenshot_block(block)
        ocr_text = ocr_from_base64(screenshot_b64) if screenshot_b64 else ""

        # Skip result/feedback pages (already answered) — require multiple indicators
        if ocr_text:
            result_hits = sum(1 for kw in [
                "得分", "本题得分", "解析",
            ] if kw in ocr_text)
            if result_hits >= 2 or "答题卡" in ocr_text:
                print("    检测到答题结果页，跳过")
                return None

        # Use OCR text for type detection and stem
        q_type, options, option_els = await self._extract_type_and_options(
            block, ocr_text=ocr_text)

        input_el = None
        if q_type == "fillin":
            try:
                input_el = await block.query_selector(
                    "input[type='text'], textarea, [contenteditable='true']")
            except Exception:
                pass

        # Use OCR text if available and meaningful, otherwise fall back to DOM
        if ocr_text and len(ocr_text) > 3:
            stem = ocr_text
        elif dom_stem and len(dom_stem) >= 3:
            stem = dom_stem
        else:
            return None

        return {
            "stem": stem,
            "q_type": q_type,
            "options": options,
            "option_els": option_els,
            "input_el": input_el,
        }

    async def _screenshot_block(self, block) -> str | None:
        """Take a screenshot of a question block + stem area above it.

        Extends the clip region upward to capture the question stem text
        that may be in a separate DOM element above the options block.
        """
        try:
            box = await block.bounding_box()
            if not box:
                return None
            # Extend upward to capture stem text above the option block
            expand_up = min(box["y"], 200)
            clip = {
                "x": max(0, box["x"] - 20),
                "y": max(0, box["y"] - expand_up),
                "width": min(box["width"] + 40, 1920),
                "height": min(box["height"] + expand_up + 20, 1080),
            }
            data = await self.page.screenshot(type="png", clip=clip)
            return base64.b64encode(data).decode("ascii")
        except Exception:
            # Fallback: screenshot the block element directly
            try:
                data = await block.screenshot(type="png")
                return base64.b64encode(data).decode("ascii")
            except Exception:
                return None

    async def _extract_stem(self, block) -> str:
        """Extract question stem text from a question block.

        Tries dedicated stem selectors first, then falls back to the block's
        text with option-like lines stripped out.
        """
        for sel in STEM_SELECTORS:
            try:
                el = await block.query_selector(sel)
                if el:
                    t = clean_text(await el.inner_text())
                    if t:
                        return t
            except Exception:
                continue

        # Fallback: block's full text, minus option-marked lines
        try:
            raw = await block.inner_text()
        except Exception:
            return ""

        return self._strip_option_lines(raw)

    @staticmethod
    def _strip_option_lines(text: str) -> str:
        """Remove lines that look like options (A. xxx  B. yyy  C. zzz) from text.

        Keeps the non-option portion as the stem.
        """
        # Split into lines and classify
        stem_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Skip pure option lines: starts with A-H followed by .、．etc.
            if re.match(r"^[A-H][\.\、\．\:：\s]", stripped):
                continue
            # Skip button labels
            if stripped in {"提交", "确认", "关闭", "跳过", "取消", "完成", "知道了", "下一题", "上一题"}:
                continue
            stem_lines.append(stripped)

        result = " ".join(stem_lines).strip()
        # Clean up "A xxx B yyy C zzz" pattern that's all on one line
        # This handles the common "A option1 B option2 C option3 D option4" format
        result = re.sub(
            r"\s+[A-H][\.\、\．\:：]\s*\S+",
            "",
            result,
        )
        return result.strip()

    async def _extract_type_and_options(self, block, ocr_text: str = ""):
        """Determine question type and extract options from a block.

        Uses OCR text (real readable text) for type detection when available,
        falls back to scrambled DOM text.

        Returns (q_type, options_text_list, option_elements_list).
        """
        block_text = ""
        try:
            block_text = clean_text(await block.inner_text())
        except Exception:
            pass

        # Use OCR text for type detection if available (bypasses font obfuscation)
        detect_text = ocr_text if ocr_text else block_text

        option_els = await self._find_options_in_block(block)
        options = []
        filtered_els = []
        nav_texts = {"上一题", "下一题", "上一页", "下一页", "提交", "交卷", "已提交", "已答"}
        for el in option_els:
            try:
                # Check raw text first to filter nav (before clean strips "提交")
                raw = (await el.inner_text() or "").strip()
                if raw in nav_texts:
                    continue
                text = clean_option_text(await el.inner_text())
                if text and text not in nav_texts:
                    if text not in options:
                        options.append(text)
                        filtered_els.append(el)
                elif not text:
                    # Text-less element (e.g. SVG icon for ✓/✗)
                    filtered_els.append(el)
                    options.append(f"[图标选项{len(options) + 1}]")
            except Exception:
                continue

        has_input = False
        try:
            has_input = bool(await block.query_selector(
                "input[type='text'], textarea, [contenteditable='true']"))
        except Exception:
            pass

        lowered = detect_text.lower()

        # Type detection — use OCR text (real) when available
        if "判断" in detect_text:
            return "truefalse", options, filtered_els
        if "多选" in detect_text:
            return "multiple", options, filtered_els
        if any(word in detect_text for word in ["正确", "错误", "对错"]):
            if len(options) <= 4:
                return "truefalse", options, filtered_els
        if "填空" in detect_text or has_input:
            return "fillin", options, filtered_els
        if "单选" in detect_text and options:
            return "single", options, filtered_els
        if len(options) >= 2:
            joined = "".join(options).lower()
            if len(options) == 2 and any(
                word in joined for word in ["正确", "错误", "true", "false", "对", "错"]
            ):
                return "truefalse", options, filtered_els
            # Check input types to distinguish single vs multiple
            try:
                radio_count = len(await block.query_selector_all(
                    "input[type='radio']"))
                checkbox_count = len(await block.query_selector_all(
                    "input[type='checkbox']"))
                if checkbox_count > radio_count:
                    return "multiple", options, filtered_els
            except Exception:
                pass
            if "multiple" in lowered:
                return "multiple", options, filtered_els
            return "single", options, filtered_els
        if has_input:
            return "fillin", options, filtered_els
        return "unknown", options, filtered_els

    async def _find_options_in_block(self, block):
        """Find option elements within a question block.

        Returns list of visible, text-bearing or clickable option element handles.
        """
        best = []
        nav_texts = {"上一题", "下一题", "上一页", "下一页", "提交", "交卷", "已提交", "已答"}
        for sel in EXERCISE_OPTION_SELECTORS:
            try:
                els = await block.query_selector_all(sel)
            except Exception:
                continue
            filtered = []
            for el in els:
                try:
                    if not await el.is_visible():
                        continue
                    text = clean_option_text(await el.inner_text())
                    # Skip navigation elements masquerading as options
                    if text and text in nav_texts:
                        continue
                    if text:
                        filtered.append(el)
                except Exception:
                    continue
            if not filtered:
                continue
            if len(filtered) == 1 and self._count_option_markers(
                await filtered[0].inner_text()
            ) >= 2:
                continue
            if len(filtered) >= 2:
                return filtered
            if not best:
                best = filtered

        # Fallback: look for icon-based true/false options (✓ ✗ custom UI)
        if len(best) < 2:
            for sel in [
                "[class*='option-item']", "[class*='choice-item']",
                "[class*='true-false'] [class*='item']",
                "[class*='judge'] [class*='item']",
                "[class*='option'] > *",
                "[class*='answer'] > *",
            ]:
                try:
                    els = await block.query_selector_all(sel)
                except Exception:
                    continue
                visible = []
                for el in els:
                    try:
                        if not await el.is_visible():
                            continue
                        visible.append(el)
                    except Exception:
                        continue
                if len(visible) >= 2:
                    best = visible
                    print(f"    图标选项模式: 找到 {len(best)} 个选项 ({sel})")
                    break
                if len(visible) > len(best):
                    best = visible

        # Ultimate fallback: grab all visible clickable child elements
        if len(best) < 2:
            try:
                children = await block.evaluate_handle("""
                    block => {
                        const clickable = [];
                        const walk = (node, depth) => {
                            if (depth > 5) return;
                            for (const child of node.children) {
                                const style = window.getComputedStyle(child);
                                const rect = child.getBoundingClientRect();
                                if (rect.width > 15 && rect.height > 15 &&
                                    style.visibility !== 'hidden' && style.display !== 'none') {
                                    const tag = child.tagName;
                                    const cls = child.className || '';
                                    const hasCursor = style.cursor === 'pointer';
                                    const hasOnClick = child.onclick !== null || child.getAttribute('onclick');
                                    const isButton = tag === 'BUTTON' || tag === 'A';
                                    const hasRadio = child.querySelector('input[type="radio"], input[type="checkbox"]');
                                    const isLabel = tag === 'LABEL';
                                    const isDiv = tag === 'DIV' || tag === 'SPAN';
                                    // For divs/spans, require cursor pointer or onclick to count
                                    if (isDiv && !hasCursor && !hasOnClick && !hasRadio) {
                                        // Still walk children but don't add this
                                        walk(child, depth + 1);
                                        continue;
                                    }
                                    if (hasCursor || hasOnClick || isButton || hasRadio || isLabel || isDiv) {
                                        clickable.push(child);
                                    }
                                }
                                walk(child, depth + 1);
                            }
                        };
                        walk(block, 0);
                        // Also collect all radio/checkbox inputs directly
                        const radios = block.querySelectorAll('input[type="radio"], input[type="checkbox"]');
                        for (const r of radios) {
                            if (r.getBoundingClientRect().width > 0 && !clickable.includes(r)) {
                                clickable.push(r);
                            }
                        }
                        return clickable;
                    }
                """)
                if children:
                    count = await children.evaluate("arr => arr.length")
                    for i in range(min(count, 10)):
                        try:
                            child = await children.evaluate_handle(
                                f"arr => arr[{i}]", children)
                            el = child.as_element()
                            if el:
                                best.append(el)
                        except Exception:
                            continue
                if best:
                    print(f"    兜底模式: 找到 {len(best)} 个可点击元素")
                else:
                    # Debug: dump block info
                    try:
                        tag = await block.evaluate("el => el.tagName")
                        cls = await block.evaluate("el => el.className || ''")
                        child_count = await block.evaluate("el => el.children.length")
                        text_sample = (await block.inner_text())[:100]
                        print(f"    调试: block=<{tag} class='{cls}' children={child_count}> text={text_sample}")
                    except Exception:
                        pass
            except Exception as exc:
                print(f"    兜底异常: {exc}")

        return best

    @staticmethod
    def _count_option_markers(text: str) -> int:
        return len(re.findall(r"(?:^|\s)[A-H](?:[\.\、\．\:：\s])", " " + text))

    # -- answering ----------------------------------------------------------------

    async def _answer_question(self, block, q_info: dict, solver,
                                 answer_delay: int, state: dict) -> bool:
        """Solve a single question and click the answer."""
        q_type = q_info["q_type"]
        options = q_info["options"]
        option_els = q_info["option_els"]
        stem = q_info["stem"]

        if state["attempts"] >= 3:
            print(f"    同一题已尝试 {state['attempts']} 次，跳过")
            return False

        if q_type == "unknown":
            print("    无法识别题型，跳过")
            return False

        await asyncio.sleep(answer_delay)

        # Call solver with OCR'd real text (not scrambled DOM text)
        try:
            answer = solver.solve(
                stem, options, q_type,
                failed_answers=sorted(state["failed"]),
                attempt_no=state["attempts"] + 1,
            )
        except Exception as exc:
            print(f"    解题器调用失败: {exc}")
            return False

        # Apply answer
        success = False
        try:
            if q_type == "single":
                idx = answer if isinstance(answer, int) else -1
                if 0 <= idx < len(option_els):
                    success = await self._click_option(option_els[idx])
                    label = chr(65 + idx) if success else "?"
                    print(f"    单选 → {label} {'✓' if success else '✗'}")
                else:
                    print(f"    单选答案索引 {idx} 超出选项范围 (0-{len(option_els)-1})")

            elif q_type == "multiple":
                if isinstance(answer, list):
                    letters = []
                    for idx in answer:
                        if isinstance(idx, int) and 0 <= idx < len(option_els):
                            ok = await self._click_option(option_els[idx])
                            letters.append(chr(65 + idx))
                            if ok:
                                await asyncio.sleep(0.3)
                    success = len(letters) > 0
                    print(f"    多选 → {','.join(letters)} {'✓' if success else '✗'}")
                else:
                    print(f"    多选答案格式错误: {type(answer).__name__}")

            elif q_type == "truefalse":
                if isinstance(answer, bool):
                    idx = 0 if answer else 1
                elif isinstance(answer, int):
                    idx = answer
                else:
                    idx = -1
                label = "正确" if answer is True else ("错误" if answer is False else "?")
                if 0 <= idx < len(option_els):
                    success = await self._click_option(option_els[idx])
                    terminal_label = f"{label}(idx={idx})"
                print(f"    判断 → {label} {'✓' if success else '✗'}")

            elif q_type == "fillin":
                inp = q_info.get("input_el")
                if inp and isinstance(answer, str) and answer.strip():
                    try:
                        if await inp.get_attribute("contenteditable") == "true":
                            await inp.fill("")
                            await inp.type(answer.strip())
                        else:
                            await inp.fill(answer.strip())
                        success = True
                    except Exception:
                        pass
                print(f"    填空 → {(answer or '')[:40] if isinstance(answer, str) else '?'} {'✓' if success else '✗'}")
        except Exception as exc:
            print(f"    作答操作异常: {exc}")

        if success:
            # Click per-question submit/confirm button (NOT "下一题")
            try:
                for scope in [self.page, block, *self.page.frames]:
                    for sel in [
                        "button:has-text('提交')", "button:has-text('确定')",
                        "button:has-text('确认')",
                        "[class*='submit-btn']", "[class*='confirm-btn']",
                    ]:
                        btns = await scope.query_selector_all(sel)
                        for btn in btns:
                            try:
                                if not await btn.is_visible():
                                    continue
                                text = (await btn.inner_text() or "").strip()
                                if text in {"已提交", "已答", "已作答", "已完成"}:
                                    continue
                                print(f"    点击按钮: {text[:20]}")
                                await self._safe_click(btn)
                                await asyncio.sleep(1)
                                raise StopIteration()
                            except StopIteration:
                                raise
                            except Exception:
                                continue
            except StopIteration:
                pass
            except Exception:
                pass

            # Detect if answer was wrong (feedback on page)
            is_wrong = await self._detect_wrong_answer()
            if is_wrong:
                print(f"    回答错误，准备重试")
                state["attempts"] += 1
                try:
                    normalized = solver.normalize_answer(answer, q_type, options)
                    if normalized:
                        state["failed"].add(normalized)
                        print(f"    已记录错误答案: {normalized}")
                except Exception:
                    pass
                # Click "下一题" to dismiss the feedback and retry
                await self._dismiss_wrong_feedback()
                return False

            state["attempts"] = 0
            state["failed"].clear()
            return True
        else:
            state["attempts"] += 1
            try:
                normalized = solver.normalize_answer(answer, q_type, options)
                if normalized:
                    state["failed"].add(normalized)
                    print(f"    已记录错误答案: {normalized}")
            except Exception:
                pass
            return False

    # -- feedback detection -------------------------------------------------------

    async def _detect_wrong_answer(self) -> bool:
        """Check if the page shows 'wrong answer' feedback after submission."""
        wrong_markers = [
            "回答错误", "答错", "不正确", "未答对",
            "重新作答", "请重试", "再试一次",
        ]
        try:
            for scope in [self.page, *self.page.frames]:
                text = await scope.inner_text()
                for marker in wrong_markers:
                    if marker in text:
                        return True
        except Exception:
            pass
        return False

    async def _dismiss_wrong_feedback(self):
        """After wrong answer, click dismiss/下一题 to clear feedback."""
        for scope in [self.page, *self.page.frames]:
            for sel in [
                "button:has-text('下一题')", "button:has-text('知道了')",
                "button:has-text('关闭')", "button:has-text('确定')",
                "[class*='next']", "[class*='close']",
            ]:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        text = (await btn.inner_text() or "").strip()
                        if text in {"已提交", "已答"}:
                            continue
                        print(f"    关闭反馈: {text[:20]}")
                        await self._safe_click(btn)
                        await asyncio.sleep(1.5)
                        return
                except Exception:
                    continue

    # -- clicking helpers --------------------------------------------------------

    async def _click_option(self, option_el, force_check: bool = False) -> bool:
        """Click an option element using multiple fallback strategies.

        Tries: inner input click → direct click → JS click → JS force-check.
        force_check=True also verifies the radio is checked after clicking.
        Returns True if any strategy likely succeeded.
        """
        clicked = False

        # Strategy 1: click inner input/label/radio/checkbox
        try:
            inner = await option_el.query_selector(
                "input, label, [role='radio'], [role='checkbox'], "
                ".el-radio, .el-checkbox, .el-radio__input, .el-checkbox__input, "
                ".ant-radio, .ant-checkbox"
            )
            if inner and await inner.is_visible():
                try:
                    await inner.click(timeout=3000)
                    clicked = True
                except Exception:
                    try:
                        await inner.evaluate(
                            "node => { node.scrollIntoView({block: 'center'}); node.click(); }")
                        clicked = True
                    except Exception:
                        pass
        except Exception:
            pass

        # Strategy 2: direct click on the element
        if not clicked:
            try:
                if await option_el.is_visible():
                    await option_el.click(timeout=3000)
                    clicked = True
            except Exception:
                pass

        # Strategy 3: JS click
        if not clicked:
            try:
                await option_el.evaluate(
                    "node => { node.scrollIntoView({block: 'center'}); node.click(); }")
                clicked = True
            except Exception:
                pass

        # Strategy 4: force-check radio/checkbox (always run as safety net)
        try:
            result = await option_el.evaluate("""
                node => {
                    // Find or create a checkable input
                    const input = node.querySelector('input[type="radio"], input[type="checkbox"]');
                    if (input) {
                        input.checked = true;
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        return 'checked_input';
                    }
                    if (node.tagName === 'INPUT' && (node.type === 'radio' || node.type === 'checkbox')) {
                        node.checked = true;
                        node.dispatchEvent(new Event('change', {bubbles: true}));
                        node.dispatchEvent(new Event('input', {bubbles: true}));
                        return 'checked_self';
                    }
                    // Maybe the option is a div/button — try to click it via JS
                    // and look for a nearby input
                    const parent = node.parentElement;
                    if (parent) {
                        const siblingInput = parent.querySelector('input[type="radio"], input[type="checkbox"]');
                        if (siblingInput) {
                            siblingInput.checked = true;
                            siblingInput.dispatchEvent(new Event('change', {bubbles: true}));
                            return 'checked_sibling';
                        }
                    }
                    // Last resort: add active/selected class
                    node.classList.add('active', 'selected', 'checked', 'is-checked');
                    node.setAttribute('aria-checked', 'true');
                    node.dispatchEvent(new Event('click', {bubbles: true}));
                    return 'marked_active';
                }
            """)
            if result:
                clicked = True
        except Exception:
            pass

        # Strategy 5: coordinate-based mouse click (simulates real user click)
        try:
            box = await option_el.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                await self.page.mouse.click(x, y)
                await asyncio.sleep(0.2)
                clicked = True
        except Exception:
            pass

        return clicked

    async def _safe_click(self, el) -> bool:
        """Multi-strategy click: inner element → direct → JS evaluate."""
        try:
            inner = await el.query_selector(
                "input, button, label, [role='button'], .el-button, .ant-btn")
            if inner and await inner.is_visible():
                try:
                    await inner.click(timeout=3000)
                    return True
                except Exception:
                    await inner.evaluate(
                        "node => { node.scrollIntoView({block: 'center'}); node.click(); }")
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
            await el.evaluate(
                "node => { node.scrollIntoView({block: 'center'}); node.click(); }")
            return True
        except Exception:
            return False

    # -- submission ---------------------------------------------------------------

    async def _click_exercise_submit(self) -> bool:
        """Find and click the exercise submit/submit-paper button."""
        for scope in [self.page, *self.page.frames]:
            for sel in EXERCISE_SUBMIT_SELECTORS:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        text = clean_text(await btn.inner_text())
                        print(f"  点击提交按钮: {text[:30]}")
                        await self._safe_click(btn)
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue
        return False

    async def _handle_confirm_dialog(self) -> bool:
        """Handle post-submit confirmation dialogs."""
        for _ in range(5):
            await asyncio.sleep(0.8)
            for scope in [self.page, *self.page.frames]:
                for sel in EXERCISE_CONFIRM_SELECTORS:
                    try:
                        btn = await scope.query_selector(sel)
                        if btn and await btn.is_visible():
                            text = clean_text(await btn.inner_text())
                            if "取消" in text:
                                continue
                            print(f"  处理确认弹窗: {text[:20]}")
                            await self._safe_click(btn)
                            await asyncio.sleep(1)
                            return True
                    except Exception:
                        continue
        return False

    # -- pagination: per-question ("下一题") -------------------------------------

    async def _has_next_question(self) -> bool:
        """Check if there is a visible '下一题' button (per-question navigation)."""
        for scope in [self.page, *self.page.frames]:
            for sel in [
                "button:has-text('下一题')", "a:has-text('下一题')",
                "[class*='next-question']", "[class*='next_topic']",
            ]:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        return True
                except Exception:
                    continue
        return False

    async def _go_next_question(self) -> bool:
        """Click the '下一题' button and wait for the next question to load."""
        for scope in [self.page, *self.page.frames]:
            for sel in [
                "button:has-text('下一题')", "a:has-text('下一题')",
                "[class*='next-question']", "[class*='next_topic']",
            ]:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        print("  进入下一题…")
                        try:
                            await btn.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        await self._safe_click(btn)
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue
        return False

    # -- pagination: page-level ("下一页") ---------------------------------------

    async def _has_next_page(self) -> bool:
        """Check if there is a visible '下一页' button (page-level navigation)."""
        for scope in [self.page, *self.page.frames]:
            for sel in EXERCISE_NEXT_PAGE_SELECTORS:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        return True
                except Exception:
                    continue
        return False

    async def _go_next_page(self) -> bool:
        """Click the '下一页' button and wait for the page to update."""
        for scope in [self.page, *self.page.frames]:
            for sel in EXERCISE_NEXT_PAGE_SELECTORS:
                try:
                    btn = await scope.query_selector(sel)
                    if btn and await btn.is_visible():
                        print("  翻到下一页…")
                        try:
                            await btn.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        await self._safe_click(btn)
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue
        return False
