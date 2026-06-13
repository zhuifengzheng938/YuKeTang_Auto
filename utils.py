"""Pure utility functions — no browser dependency, no class.

Extracted from bot.py to keep modules focused and testable.
"""

import re
from urllib.parse import urljoin, urlparse, parse_qs


# -- URL helpers -----------------------------------------------------------

def normalize_lesson_url(href: str, page_url: str = None) -> str | None:
    """Resolve relative href to absolute URL, strip query string."""
    if not href:
        return None
    base = page_url or "https://www.yuketang.cn"
    normalized = urljoin(base, href)
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def extract_course_scope(url: str) -> dict | None:
    """Parse course identity from a yuketang URL.

    Returns dict with keys: host, course_id, path_prefix.
    Used to scope lesson links to a single course.
    """
    normalized = normalize_lesson_url(url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
    query = parse_qs(parsed.query)
    course_id = None

    # video-student/<classroom_id>/<leaf_id>
    if "video-student" in segments:
        idx = segments.index("video-student")
        if idx > 0:
            course_id = segments[idx - 1]
    # studentLog/<classroom_id>
    if not course_id and "studentLog" in segments:
        idx = segments.index("studentLog")
        if idx + 1 < len(segments):
            course_id = segments[idx + 1]
    # course/<id>
    if not course_id and "course" in segments:
        idx = segments.index("course")
        if idx + 1 < len(segments):
            course_id = segments[idx + 1]
    # classroom_id query param
    if not course_id:
        for key in ("classroom_id", "classroomId", "course_id", "courseId"):
            if key in query and query[key]:
                course_id = query[key][0]
                break
    return {
        "host": parsed.netloc,
        "course_id": course_id,
        "path_prefix": f"{parsed.scheme}://{parsed.netloc}",
    }


def url_in_course_scope(url: str, scope: dict | None) -> bool:
    """Check if *url* belongs to the same course as *scope*."""
    if not scope:
        return True
    parsed = urlparse(url)
    if parsed.netloc != scope.get("host"):
        return False
    course_id = scope.get("course_id")
    if not course_id:
        return True
    segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
    return course_id in segments


# -- Text helpers ----------------------------------------------------------

def clean_text(text: str) -> str:
    """Join non-empty lines, remove known button-label noise."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in {"提交", "确认", "关闭", "跳过", "取消", "完成", "知道了"}:
            continue
        lines.append(line)
    return " ".join(lines).strip()


def clean_option_text(text: str) -> str:
    """Like clean_text + strip leading 'A.' 'B、' prefix."""
    text = clean_text(text)
    if not text:
        return ""
    text = re.sub(r"^[A-H][\.、．:：\s]+", "", text).strip()
    return text


# -- Lesson classification -------------------------------------------------

def lesson_text_is_finished(text: str) -> bool:
    """Heuristic: does *text* indicate a completed lesson?"""
    if not text:
        return False
    # "未完成"/"进行中" → not finished
    if any(flag in text for flag in ["未完成", "未学习", "未开始", "未读", "进行中"]):
        return False
    # percentage-based signals
    if any(flag in text for flag in ["100%", "99%", "98%"]):
        return True
    # short text (<60 chars) with explicit completion markers is reliable;
    # longer text may be an aggregate container
    if len(text) < 60:
        return any(flag in text for flag in [
            "已完成", "学习完成", "完成学习", "观看完成", "已看完",
            "已学完", "已学习", "已读",
        ])
    return False


def is_summary_node(text: str, href=None) -> bool:
    """Detect chapter/section summary nodes (not real leaf lessons).

    Matches patterns like:
    "教学大纲 等 包含6章，31小节，共计43个学习单元 展开 进行中"
    """
    if not text:
        return False
    if href and "video-student" in href:
        return False
    summary_flags = [
        "包含", "小节", "学习单元", "共计", "教学大纲",
        "考核截止", "修读说明", "修读要求", "课程介绍",
    ]
    hits = sum(1 for f in summary_flags if f in text)
    return hits >= 2 and not href


def lesson_key(href=None, text=None) -> str | None:
    """Generate a stable dedup key for a lesson."""
    if href:
        return f"url::{href}"
    if text:
        return f"text::{text[:80]}"
    return None
