import os

# Try to import local overrides (gitignored, never pushed)
try:
    from config_local import *  # noqa: F403
except ImportError:
    pass

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "gpt-5.5")
ANTHROPIC_FALLBACK_MODEL = os.environ.get("ANTHROPIC_FALLBACK_MODEL", "claude-opus-4-6")
MODEL_WEB_SEARCH = os.environ.get("MODEL_WEB_SEARCH", "1").strip().lower() not in {"0", "false", "off", "no"}
COURSE_URL = ""          # e.g. "https://www.yuketang.cn/v2/web/course/12345"
PLAYBACK_SPEED = 2.0
ANSWER_DELAY = 3         # seconds before submitting (looks natural)
LOGIN_TIMEOUT = 120      # seconds to wait for WeChat QR scan
