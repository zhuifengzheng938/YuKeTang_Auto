"""Local OCR wrapper using EasyOCR for reading anti-scraping-obfuscated text.

Initializes once (expensive model load) and provides a simple callable.
Sets torch hub mirror for faster downloads in China.
"""

import io
import os

import numpy as np
from PIL import Image

# Use Tsinghua mirror for torch hub downloads (model files)
os.environ.setdefault("TORCH_HOME", os.path.expanduser("~/.cache/torch"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        print("  正在加载 EasyOCR 中文模型（首次需下载约 80MB）…")
        _reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        print("  EasyOCR 模型加载完成")
    return _reader


def ocr_from_base64(b64_data: str) -> str:
    """OCR a base64-encoded PNG image, return concatenated text lines.

    Args:
        b64_data: Base64-encoded PNG image bytes.

    Returns:
        Space-separated text lines, or empty string on failure.
    """
    import base64
    try:
        raw = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(raw))
        arr = np.array(img)
        reader = _get_reader()
        results = reader.readtext(arr, detail=0)
        return " ".join(results).strip()
    except Exception as exc:
        print(f"    OCR 识别失败: {exc}")
        return ""
