"""Exercise page handler for yuketang_bot.

Placeholder for future AI-powered exercise solving.
Detects exercise/test pages that have no video and provides an extension point.
"""

from playwright.async_api import Page


class ExerciseHandler:
    """Detect and handle standalone exercise/test pages (no video)."""

    EXERCISE_MARKERS = [
        "答题", "习题", "测验", "考试", "练习", "试卷",
        "单选题", "多选题", "判断题", "填空题",
        "提交试卷", "交卷", "开始答题",
    ]

    def __init__(self, page: Page):
        self.page = page

    def is_exercise_page(self) -> bool:
        """Check if current page is an exercise/test page (no video, has question markers)."""
        try:
            text = self.page.inner_text("body")
        except Exception:
            return False
        hits = sum(1 for m in self.EXERCISE_MARKERS if m in text)
        return hits >= 2

    async def handle(self, question_handler) -> bool:
        """Handle exercises on the current page.

        Args:
            question_handler: QuestionHandler instance for reuse (solver, extraction).

        Returns:
            True if exercises were handled, False to skip.
        """
        print("  检测到习题/测验页面")
        # TODO: Future implementation —
        # 1. Scan page for question blocks (not just modal popups)
        # 2. Extract each question's stem + options + type
        # 3. Use question_handler.solver.solve(stem, options, q_type)
        # 4. Submit answers via button clicks
        # 5. Handle pagination if multi-page exam
        print("  习题AI解题功能开发中，暂时跳过")
        return False
