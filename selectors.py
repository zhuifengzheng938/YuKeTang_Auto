"""CSS/text selectors for yuketang web elements.

All selectors used by browser, catalog, video, and question modules.
Dead speed-control selectors have been removed.
"""

# -- 题目弹窗检测 -----------------------------------------------------------
QUESTION_MODAL_SELECTORS = [
    ".question-modal", ".quiz-modal", ".exam-modal",
    ".el-dialog", ".ant-modal", ".ant-modal-content",
    "[class*='question-dialog']", "[class*='quiz-dialog']",
    "[class*='popup-question']", ".video-question",
    "[class*='danmu-question']", "[class*='inline-question']",
    "[class*='question']", "[class*='quiz']",
]

# -- 选项元素 ---------------------------------------------------------------
OPTION_SELECTORS = [
    ".option-item", ".choice-item", ".answer-option",
    ".el-radio", ".el-checkbox", ".ant-radio-wrapper", ".ant-checkbox-wrapper",
    "[class*='option-item']", "[class*='choice-item']", "[class*='option']",
    "label", "li.option", "li",
]

# -- 题干 ------------------------------------------------------------------
STEM_SELECTORS = [
    ".question-stem", ".stem", ".topic", ".subject", ".content",
    "[class*='question-stem']", "[class*='question-content']", "[class*='stem']", ".title",
]

# -- 提交按钮 ---------------------------------------------------------------
SUBMIT_SELECTORS = [
    "button:has-text('提交')", "button:has-text('确认')", "button:has-text('确定')",
    "button:has-text('完成')", ".submit-btn", ".confirm-btn", "[class*='submit']",
    "[class*='confirm']", ".el-button--primary", ".ant-btn-primary",
]

# -- 跳过 / 关闭 ------------------------------------------------------------
SKIP_SELECTORS = [
    "button:has-text('跳过')", "button:has-text('关闭')", "button:has-text('知道了')",
    "button:has-text('取消')", "[class*='close']", ".el-dialog__close", ".ant-modal-close",
]

# -- 答题反馈 ---------------------------------------------------------------
QUESTION_FEEDBACK_SELECTORS = [
    ".el-message", ".ant-message", ".ant-notification",
    "[class*='feedback']", "[class*='result']", "[class*='wrong']",
    "[class*='error']", "[class*='success']", "[class*='toast']",
]

# -- 登录成功信号 -----------------------------------------------------------
LOGIN_SUCCESS_SELECTORS = [
    "[class*='user']", "[class*='avatar']", "img[class*='avatar']",
    "[class*='profile']", "[class*='logout']",
]
LOGIN_SUCCESS_TEXTS = ["退出登录", "个人中心"]

# -- "开始学习" 入口 -----------------------------------------------
START_STUDY_SELECTORS = [
    "button:has-text('开始学习')", "button:has-text('继续学习')", "button:has-text('进入学习')",
    "button:has-text('去学习')", "a:has-text('开始学习')", "a:has-text('继续学习')",
    "a:has-text('进入学习')", "a:has-text('去学习')",
]

# -- 课时链接入口 -----------------------------------------------------------
LESSON_ENTRY_SELECTORS = [
    "a[href*='video-student']", "a[href*='leafId']", "a[href*='lesson']", "a[href*='learn']",
    "[class*='lesson-item']", "[class*='chapter-item']", "[class*='video-item']", "[class*='leaf']",
]

# -- 下一节 -----------------------------------------------------------------
NEXT_LESSON_SELECTORS = [
    "button:has-text('下一节')", "a:has-text('下一节')",
    "button:has-text('下一个')", "a:has-text('下一个')",
    "button:has-text('下一课')", "a:has-text('下一课')",
    "button:has-text('下一视频')", "a:has-text('下一视频')",
]

# -- 目录展开 ---------------------------------------------------------------
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

# -- 返回目录 ---------------------------------------------------------------
BACK_TO_CATALOG_SELECTORS = [
    "button:has-text('返回')", "a:has-text('返回')",
    "button:has-text('返回课程')", "a:has-text('返回课程')",
    "button:has-text('课程主页')", "a:has-text('课程主页')",
    "button:has-text('全部课时')", "a:has-text('全部课时')",
]

# -- 目录中课时元素 ---------------------------------------------------------
CATALOG_LESSON_SELECTOR = (
    "a[href*='video-student'], a[href*='leafId'], a[href*='lesson'], a[href*='learn'], "
    "[class*='lesson-item'], [class*='leaf-item'], [class*='video-item'], "
    "[class*='chapter-item'], [class*='activity__wrap'], [class*='content-box'] section"
)
