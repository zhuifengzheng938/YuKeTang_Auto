import json
import re

import anthropic


class QuestionSolver:
    def __init__(self, api_key: str, base_url: str, model: str,
                 web_search: bool = True, fallback_model: str | None = None):
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url.rstrip("/")
        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = model
        self.fallback_model = fallback_model
        self.web_search = web_search
        self._search_downgraded = False
        self._image_downgraded = False
        self.last_image_question: str | None = None

    def solve(
        self,
        question_text: str,
        options: list,
        q_type: str,
        failed_answers=None,
        attempt_no: int = 1,
        image_base64: str | None = None,
    ):
        """Ask the model for an answer and parse it into the format bot.py expects.

        When image_base64 is provided, the model reads the question from the
        screenshot (useful for anti-scraping font-obfuscated pages). Text params
        are still used for answer format parsing.
        """
        failed_answers = {item for item in (failed_answers or []) if item}

        if image_base64 and self._image_downgraded:
            image_base64 = None

        if image_base64:
            prompts = [
                self._build_image_prompt(
                    q_type, len(options or []),
                    failed_answers=failed_answers, attempt_no=attempt_no,
                ),
                self._build_image_prompt(
                    q_type, len(options or []),
                    strict_json=True,
                    failed_answers=failed_answers, attempt_no=attempt_no,
                ),
            ]
        else:
            prompts = [
                self._build_prompt(
                    question_text, options, q_type,
                    failed_answers=failed_answers, attempt_no=attempt_no,
                ),
                self._build_prompt(
                    question_text, options, q_type,
                    strict_json=True,
                    failed_answers=failed_answers, attempt_no=attempt_no,
                ),
                self._build_prompt(
                    question_text, options, q_type,
                    ultra_strict=True,
                    failed_answers=failed_answers, attempt_no=attempt_no,
                ),
            ]

        last_response = ""
        last_raw_summary = ""
        last_error = None

        for prompt in prompts:
            response, raw_summary = self._call_model(
                prompt, stream=False, image_base64=image_base64)
            last_response = response
            last_raw_summary = raw_summary

            if not response.strip():
                response, raw_summary = self._call_model(prompt, stream=True)
                last_response = response
                last_raw_summary = raw_summary

            if not response.strip():
                last_error = ValueError(f"模型返回空内容，原始响应摘要: {last_raw_summary}")
                continue

            if image_base64:
                q_text = self._extract_question_from_response(response)
                if q_text:
                    self.last_image_question = q_text

            try:
                parsed = self._parse(response, options, q_type)
            except ValueError as exc:
                last_error = exc
                continue

            normalized = self.normalize_answer(parsed, q_type, options)
            if normalized and normalized in failed_answers:
                last_error = ValueError(f"模型重复返回已知错误答案: {normalized}")
                continue
            return parsed

        if last_error:
            raise last_error
        raise ValueError(f"无法获得模型答案，最后响应: {last_response!r}，原始响应摘要: {last_raw_summary}")

    def _call_model(self, prompt: str, stream: bool = False,
                     image_base64: str | None = None):
        if image_base64:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_base64,
                    },
                },
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt

        kwargs = {
            "model": self.model,
            "max_tokens": 512,
            "system": self._build_system_prompt(),
            "messages": [{"role": "user", "content": content}],
        }

        search_enabled = self.web_search and not self._search_downgraded
        if search_enabled:
            kwargs["extra_body"] = {"web_search": True}

        if not stream:
            try:
                msg = self.client.messages.create(**kwargs)
                return self._extract_text(msg), self._summarize_raw(msg)
            except Exception as exc:
                if image_base64 and not self._image_downgraded and self._should_disable_image(exc):
                    self._image_downgraded = True
                    print("  接口不支持图片输入，已自动回退为纯文本作答")
                    return self._call_model(prompt, stream=False)
                if search_enabled and self._should_disable_search(exc):
                    self._search_downgraded = True
                    print("  模型侧联网搜索不受支持，已自动回退为普通作答")
                    kwargs.pop("extra_body", None)
                    msg = self.client.messages.create(**kwargs)
                    return self._extract_text(msg), self._summarize_raw(msg)
                if self.fallback_model and kwargs["model"] != self.fallback_model:
                    print(f"  模型 {kwargs['model']} 调用失败，回退到 {self.fallback_model}")
                    kwargs["model"] = self.fallback_model
                    if self._image_downgraded:
                        return self._call_model(prompt, stream=False)
                    msg = self.client.messages.create(**kwargs)
                    return self._extract_text(msg), self._summarize_raw(msg)
                raise

        try:
            parts = []
            final_message = None
            with self.client.messages.stream(**kwargs) as response_stream:
                try:
                    for text in response_stream.text_stream:
                        if text:
                            parts.append(text)
                except Exception:
                    pass
                try:
                    final_message = response_stream.get_final_message()
                except Exception:
                    final_message = None
            streamed_text = "".join(parts).strip()
            if streamed_text:
                return streamed_text, streamed_text[:500]
            return self._extract_text(final_message), self._summarize_raw(final_message)
        except Exception as exc:
            if image_base64 and not self._image_downgraded and self._should_disable_image(exc):
                self._image_downgraded = True
                print("  接口不支持图片输入(流式)，已自动回退为纯文本作答")
                return self._call_model(prompt, stream=False)
            if search_enabled and self._should_disable_search(exc):
                self._search_downgraded = True
                print("  模型侧联网搜索不受支持，流式路径已自动回退为普通作答")
                return self._call_model(prompt, stream=False)
            if self.fallback_model and kwargs["model"] != self.fallback_model:
                print(f"  模型 {kwargs['model']} 流式调用失败，回退到 {self.fallback_model}")
                kwargs["model"] = self.fallback_model
                if self._image_downgraded:
                    return self._call_model(prompt, stream=False)
                try:
                    msg = self.client.messages.create(**kwargs)
                    return self._extract_text(msg), self._summarize_raw(msg)
                except Exception:
                    pass
            return "", f"stream 调用失败: {exc}"

    def _build_system_prompt(self) -> str:
        base = (
            "你是严谨的课程题目作答助手。请仔细阅读题目，运用你的知识认真作答。"
        )
        if self.web_search and not self._search_downgraded:
            return (
                base
                + "如果当前模型或网关支持联网搜索，请先搜索再作答；"
                + "但最终只输出题目要求的最终答案，不要输出搜索过程、引用或解释。"
            )
        return (
            base
            + "由于无法联网验证，请格外仔细地审题，根据你的知识做出最佳判断。"
            + "对于判断题，仔细分辨陈述的真伪。"
            + "不要解释，不要输出推理过程，只输出最终答案。"
        )

    @staticmethod
    def _should_disable_search(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = [
            "web_search", "web search", "extra_body",
            "unknown parameter", "extra inputs are not permitted",
            "400", "422", "unsupported",
        ]
        return any(marker in text for marker in markers)

    @staticmethod
    def _should_disable_image(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = [
            "image", "multimodal", "media", "vision",
            "unsupported", "invalid content", "content block",
            "bad response status code", "400", "422",
        ]
        return any(marker in text for marker in markers)

    def _build_prompt(
        self,
        question: str,
        options: list,
        q_type: str,
        strict_json: bool = False,
        ultra_strict: bool = False,
        failed_answers=None,
        attempt_no: int = 1,
    ) -> str:
        type_name = {
            "single": "单选题",
            "multiple": "多选题",
            "truefalse": "判断题",
            "fillin": "填空题",
        }.get(q_type, q_type)

        opts = "\n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(options or []))
        failed_block = self._build_failed_answer_block(failed_answers)
        attempt_block = f"当前是第 {attempt_no} 次作答。\n" if attempt_no > 1 else ""

        if strict_json:
            return (
                f"题型：{type_name}\n"
                f"{attempt_block}"
                f"{failed_block}"
                "请只输出一行 JSON，不要解释，不要 Markdown。\n"
                "格式必须是：{\"answer\":\"...\"}\n"
                "单选题 answer 填一个大写字母，例如 B。\n"
                "多选题 answer 填大写字母并用英文逗号分隔，例如 B,C,E。\n"
                "判断题 answer 只能填 正确 或 错误。\n"
                "填空题 answer 填最终答案。\n\n"
                f"题目：\n{question}\n\n选项：\n{opts}\n"
            )

        if ultra_strict:
            if q_type == "single":
                allowed = ",".join(chr(65 + i) for i in range(len(options or [])))
                rule = f"只输出一个字符，必须是以下之一：{allowed}。"
            elif q_type == "multiple":
                allowed = ",".join(chr(65 + i) for i in range(len(options or [])))
                rule = f"只输出正确选项字母，用英文逗号分隔；字母只能来自：{allowed}。"
            elif q_type == "truefalse":
                rule = "只输出 正确 或 错误。成立/正确->正确，不成立/错误->错误。"
            else:
                rule = "只输出最终答案。"
            return f"{attempt_block}{failed_block}{rule}\n\n{question}\n\n{opts}\n答案："

        if q_type == "single":
            return (
                f"{attempt_block}"
                f"{failed_block}"
                "请回答以下单选题。只能输出一个大写选项字母，例如 A。"
                "不要解释，不要输出其他内容。\n\n"
                f"{question}\n\n{opts}\n\n答案："
            )
        if q_type == "multiple":
            return (
                f"{attempt_block}"
                f"{failed_block}"
                "请回答以下多选题。只能输出所有正确选项的大写字母，"
                "并用英文逗号分隔，例如 A,C。不要解释，不要输出其他内容。\n\n"
                f"{question}\n\n{opts}\n\n答案："
            )
        if q_type == "truefalse":
            return (
                f"{attempt_block}"
                f"{failed_block}"
                "请仔细判断以下说法是否成立。\n"
                "如果说法成立、正确，请输出：正确\n"
                "如果说法不成立、错误，请输出：错误\n"
                "务必认真思考后再作答，不要解释。\n\n"
                f"{question}\n\n你的判断："
            )
        return (
            f"{attempt_block}"
            f"{failed_block}"
            "请回答以下填空题。只输出最终答案，不要解释，不要重复题目。\n\n"
            f"{question}\n\n答案："
        )

    def _build_image_prompt(
        self,
        q_type: str,
        option_count: int,
        strict_json: bool = False,
        failed_answers=None,
        attempt_no: int = 1,
    ) -> str:
        type_instruction = {
            "single": "这是一道单选题。请查看截图中的题目和选项，选出唯一正确答案。",
            "multiple": "这是一道多选题。请查看截图中的题目和选项，选出所有正确答案。",
            "truefalse": "这是一道判断题。请查看截图中的题目，判断正误。",
            "fillin": "这是一道填空题。请查看截图中的题目，写出答案。",
        }
        instruction = type_instruction.get(q_type, "请查看截图中的题目，选出正确答案。")

        failed_block = self._build_failed_answer_block(failed_answers)
        attempt_block = f"当前是第 {attempt_no} 次作答。\n" if attempt_no > 1 else ""

        if strict_json:
            format_rules = (
                "格式：\n"
                "题目：<你从截图中看到的完整题目文本>\n"
                "{\"answer\":\"<你的答案>\"}\n"
                "只输出这两行，不要解释，不要 Markdown。\n"
            )
        else:
            format_rules = (
                "按以下格式回复，只输出两行，不要解释：\n"
                "题目：<你从截图中看到的完整题目文本>\n"
                "答案：<你的答案>\n"
            )

        if q_type == "single":
            format_rules += (
                f"答案填一个大写字母（A-{chr(64 + option_count)}），例如 B。"
            )
        elif q_type == "multiple":
            allowed = ",".join(chr(65 + i) for i in range(option_count))
            format_rules += (
                f"答案填大写字母用英文逗号分隔，例如 {allowed[:3]}。"
            )
        elif q_type == "truefalse":
            format_rules += "答案填 正确 或 错误。"
        else:
            format_rules += "答案填最终答案文本。"

        return f"{attempt_block}{failed_block}{instruction}\n{format_rules}"

    @staticmethod
    def _extract_question_from_response(response: str) -> str | None:
        match = re.search(r"题目[：:]\s*(.+?)(?:\n|$)", response)
        if match:
            text = match.group(1).strip()
            if text and not text.startswith("{"):
                return text
        return None

    @staticmethod
    def _build_failed_answer_block(failed_answers) -> str:
        items = [item for item in (failed_answers or []) if item]
        if not items:
            return ""
        shown = "；".join(sorted(items))
        return (
            f"以下答案已经试过且错误，不要重复这些答案：{shown}。\n"
            "如果题目是单选或判断，请改选其他仍合法的答案；如果是多选，请重新组合，不要复用完全相同的答案。\n"
        )

    @staticmethod
    def normalize_answer(answer, q_type: str, options: list) -> str:
        if answer is None:
            return ""

        if q_type == "single":
            if isinstance(answer, int) and 0 <= answer < len(options or []):
                return chr(65 + answer)
            if isinstance(answer, str):
                match = re.search(r"[A-Z]", answer.upper())
                if match:
                    return match.group(0)
            return ""

        if q_type == "multiple":
            if not isinstance(answer, list):
                return ""
            letters = []
            for idx in answer:
                if isinstance(idx, int) and 0 <= idx < len(options or []):
                    letter = chr(65 + idx)
                    if letter not in letters:
                        letters.append(letter)
            return ",".join(letters)

        if q_type == "truefalse":
            if isinstance(answer, bool):
                return "正确" if answer else "错误"
            if isinstance(answer, int) and 0 <= answer < len(options or []):
                text = (options[answer] or "").strip()
                lowered = text.lower()
                if any(word in text for word in ["正确", "对"]) or lowered == "true":
                    return "正确"
                if any(word in text for word in ["错误", "错"]) or lowered == "false":
                    return "错误"
            if isinstance(answer, str):
                lowered = answer.strip().lower()
                if lowered in {"正确", "true", "yes", "对"}:
                    return "正确"
                if lowered in {"错误", "false", "no", "错"}:
                    return "错误"
            return ""

        if isinstance(answer, str):
            return re.sub(r"\s+", "", answer).strip()
        return ""

    @staticmethod
    def _extract_text(msg) -> str:
        plain = QuestionSolver._to_plain(msg)

        if isinstance(plain, str):
            stripped = plain.strip()
            if not stripped:
                return ""
            try:
                plain = json.loads(stripped)
            except Exception:
                return stripped

        for path in [
            ("content",),
            ("text",),
            ("message", "content"),
            ("choices", 0, "message", "content"),
            ("choices", 0, "text"),
            ("data", "content"),
            ("data", "text"),
            ("data", "message", "content"),
            ("output",),
            ("response",),
        ]:
            text = QuestionSolver._content_to_text(QuestionSolver._get_path(plain, path))
            if text:
                return text

        return QuestionSolver._recursive_text_search(plain).strip()

    @staticmethod
    def _to_plain(obj):
        if obj is None or isinstance(obj, (str, int, float, bool, list, tuple, dict)):
            return obj
        for method_name in ("model_dump", "dict", "to_dict"):
            method = getattr(obj, method_name, None)
            if callable(method):
                try:
                    return method()
                except Exception:
                    pass
        try:
            return vars(obj)
        except Exception:
            return str(obj)

    @staticmethod
    def _get_path(obj, path):
        cur = obj
        for key in path:
            try:
                if isinstance(key, int):
                    cur = cur[key]
                elif isinstance(cur, dict):
                    cur = cur.get(key)
                else:
                    cur = getattr(cur, key, None)
            except Exception:
                return None
            if cur is None:
                return None
        return cur

    @staticmethod
    def _content_to_text(value) -> str:
        value = QuestionSolver._to_plain(value)
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            parts = []
            for key in ("text", "content", "message", "response", "output"):
                text = QuestionSolver._content_to_text(value.get(key))
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        if isinstance(value, (list, tuple)):
            parts = []
            for item in value:
                text = QuestionSolver._content_to_text(item)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _recursive_text_search(value) -> str:
        value = QuestionSolver._to_plain(value)
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            parts = [QuestionSolver._recursive_text_search(v) for v in value]
            return "\n".join(p for p in parts if p).strip()
        if isinstance(value, dict):
            parts = []
            text_keys = {"text", "content", "message", "response", "output", "answer"}
            for key, item in value.items():
                if key in text_keys:
                    text = QuestionSolver._recursive_text_search(item)
                    if text:
                        parts.append(text)
            if parts:
                return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _summarize_raw(msg) -> str:
        try:
            plain = QuestionSolver._to_plain(msg)
            dumped = json.dumps(plain, ensure_ascii=False, default=str)
        except Exception:
            dumped = str(msg)
        dumped = re.sub(r"\s+", " ", dumped).strip()
        return dumped[:500]

    def _parse(self, response: str, options: list, q_type: str):
        response = response.strip()
        answer_text = self._extract_answer_field(response)
        if answer_text:
            response = answer_text.strip()

        if q_type == "single":
            letter = self._parse_single_letter(response, len(options))
            if letter is not None:
                return letter
            for i, option in enumerate(options):
                if option and option in response:
                    return i
            raise ValueError(f"无法解析单选答案: {response!r}")

        if q_type == "multiple":
            indices = self._parse_multiple_letters(response, len(options))
            if indices:
                return indices
            matched = []
            for i, option in enumerate(options):
                if option and option in response:
                    matched.append(i)
            if matched:
                return matched
            raise ValueError(f"无法解析多选答案: {response!r}")

        if q_type == "truefalse":
            normalized = response.strip().lower()
            # DEBUG: print raw model response
            print(f"    [DEBUG] 模型原始输出: {response!r}")
            if response == "正确" or normalized in {"true", "yes", "对"}:
                return True
            if response == "错误" or normalized in {"false", "no", "错"}:
                return False
            if "正确" in response:
                return True
            if "错误" in response:
                return False
            raise ValueError(f"无法解析判断题答案: {response!r}")

        cleaned = response.splitlines()[0].strip()
        cleaned = re.sub(r"^(答案[:：]?|填空[:：]?)\s*", "", cleaned)
        return cleaned or response.strip()

    @staticmethod
    def _extract_answer_field(response: str) -> str:
        try:
            obj = json.loads(response)
            if isinstance(obj, dict):
                for key in ("answer", "答案", "result"):
                    value = obj.get(key)
                    if isinstance(value, str):
                        return value
                    if isinstance(value, list):
                        return ",".join(str(v) for v in value)
        except Exception:
            pass

        match = re.search(r"(?:答案|正确答案|answer)\s*[:：]\s*([^\n\r]+)", response, flags=re.I)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _parse_single_letter(response: str, option_count: int):
        if option_count <= 0:
            return None
        allowed = chr(64 + option_count)
        match = re.search(r"\b([A-%s])\b" % allowed, response.upper())
        if match:
            return ord(match.group(1)) - ord("A")
        compact = re.sub(r"[^A-Z]", "", response.upper())
        if len(compact) == 1 and "A" <= compact <= allowed:
            return ord(compact) - ord("A")
        return None

    @staticmethod
    def _parse_multiple_letters(response: str, option_count: int):
        if option_count <= 0:
            return []
        allowed = chr(64 + option_count)
        upper = response.upper()

        compact = re.sub(r"[^A-%s]" % allowed, "", upper)
        if compact and len(compact) <= option_count:
            seen = []
            for ch in compact:
                idx = ord(ch) - ord("A")
                if idx not in seen:
                    seen.append(idx)
            return seen

        matches = re.findall(r"\b([A-%s])\b" % allowed, upper)
        seen = []
        for ch in matches:
            idx = ord(ch) - ord("A")
            if idx not in seen:
                seen.append(idx)
        return seen
