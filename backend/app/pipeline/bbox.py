"""Derive a field's bounding box from docTR word geometry by matching the extracted value
against the document's words (CONSIGNE: bbox derived from docTR boxes, not guessed by the LLM)."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from .ocr import OcrWord

_MATCH_THRESHOLD = 65.0


def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s).lower()


def _union(words: list[OcrWord]) -> list[float]:
    xs0 = [w.bbox[0] for w in words]
    ys0 = [w.bbox[1] for w in words]
    xs1 = [w.bbox[0] + w.bbox[2] for w in words]
    ys1 = [w.bbox[1] + w.bbox[3] for w in words]
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    return [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)]


def derive_bbox(value: str, words: list[OcrWord], page: int = 0) -> list[float] | None:
    """Best-effort bbox [x%, y%, w%, h%] for ``value`` on ``page``; None if no decent match."""
    target = _norm(value)
    if not target:
        return None

    page_words = [w for w in words if w.page == page and _norm(w.text)]
    if not page_words:
        return None

    n = max(1, len(value.split()))
    best_score = 0.0
    best_window: list[OcrWord] = []

    for size in {max(1, n - 1), n, n + 1}:
        for i in range(len(page_words) - size + 1):
            window = page_words[i : i + size]
            joined = _norm("".join(w.text for w in window))
            score = fuzz.ratio(target, joined)
            if score > best_score:
                best_score = score
                best_window = window

    if best_score >= _MATCH_THRESHOLD and best_window:
        return _union(best_window)
    return None
