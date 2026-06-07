import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://cloud.hongqiye.com")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MODEL_WEB_SEARCH = os.environ.get("MODEL_WEB_SEARCH", "0").strip().lower() not in {"0", "false", "off", "no"}
COURSE_URL = ""          # e.g. "https://www.yuketang.cn/v2/web/course/12345"
PLAYBACK_SPEED = 2.0
ANSWER_DELAY = 3         # seconds before submitting (looks natural)
LOGIN_TIMEOUT = 120      # seconds to wait for WeChat QR scan
