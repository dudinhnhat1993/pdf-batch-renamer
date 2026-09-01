"""Định vị 1 chuỗi giá trị trên trang PDF: dò chuỗi từ khớp và trả bbox gộp.

Dùng cho 2 việc: ghi provenance (giá trị này nằm ở đâu trên trang) và Visual Rule
Builder (user bôi chọn text -> biết đang trỏ vào những từ nào).
"""

from __future__ import annotations

import re

from .models import PageText, Word


def _tokens(value: str) -> list[str]:
    return [t for t in re.split(r"\s+", (value or "").strip()) if t]


def _norm(text: str) -> str:
    """Bỏ ký tự không phải chữ/số để so khớp bền với dấu câu và khoảng trắng lạ."""
    return re.sub(r"[^0-9a-zA-ZÀ-ỹ]+", "", text or "").casefold()


def find_word_span(page: PageText, value: str) -> list[Word]:
    """Tìm dãy từ liên tiếp trên trang khớp với value. Không thấy -> danh sách rỗng."""
    tokens = [_norm(t) for t in _tokens(value)]
    tokens = [t for t in tokens if t]
    if not tokens or not page.words:
        return []

    words = page.words
    normed = [_norm(w.text) for w in words]
    target = "".join(tokens)

    for start in range(len(words)):
        if not normed[start]:
            continue
        acc = ""
        for end in range(start, min(start + len(tokens) + 6, len(words))):
            acc += normed[end]
            if acc == target:
                return words[start : end + 1]
            if not target.startswith(acc):
                break
    return []


def bbox_of(words: list[Word]) -> tuple[float, float, float, float] | None:
    """Bbox gộp của một dãy từ."""
    if not words:
        return None
    return (
        min(w.x0 for w in words),
        min(w.y0 for w in words),
        max(w.x1 for w in words),
        max(w.y1 for w in words),
    )


def locate(page: PageText, value: str) -> tuple[float, float, float, float] | None:
    """Bbox của value trên trang, hoặc None nếu không định vị được."""
    return bbox_of(find_word_span(page, value))
