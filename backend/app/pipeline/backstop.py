"""Deterministic field repair for invoices.

The OCR amounts and dates on receipts are highly regular (``RM 30.90``, ``18-11-18``),
so when the LLM misses or is unsure about ``total``/``date`` we backfill from regex.
Pure functions, no GPU/LLM — exercised directly in tests."""

from __future__ import annotations

import re

from ..schema_def import PLACEHOLDER, ValidatedField
from ..summary_calc import parse_money

# A currency amount, optional symbol/code + ##.## . Captured group is the symbol+number.
_AMOUNT = re.compile(
    r"((?:RM|MYR|USD|EUR|\$|€)\s*)?(\d[\d,]*\.\d{2})\b",
    re.IGNORECASE,
)
_TOTAL_LINE = re.compile(r"\b(grand\s+total|amount\s+due|total\s+inclusive|total)\b", re.IGNORECASE)
_EXCLUDE_LINE = re.compile(r"\b(sub[\s-]?total|change|round(?:ing)?|cash|tender)\b", re.IGNORECASE)

_DATE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b"
)


def _amount_str(match: re.Match) -> str:
    sym = (match.group(1) or "").strip()
    num = match.group(2)
    return f"{sym} {num}".strip() if sym else num


def _total_line_matches(text: str) -> list[re.Match]:
    """Amounts found on 'total'/'amount due' lines (excluding subtotal/change/cash)."""
    preferred: list[re.Match] = []
    for line in text.splitlines():
        if _EXCLUDE_LINE.search(line):
            continue
        if _TOTAL_LINE.search(line):
            preferred.extend(_AMOUNT.finditer(line))
    return preferred


def find_total_line_amount(text: str) -> str | None:
    """The amount on an explicit total line, or None if the document has no such line."""
    matches = _total_line_matches(text)
    if not matches:
        return None
    best = max(matches, key=lambda m: float(m.group(2).replace(",", "")))
    return _amount_str(best)


def find_amount(text: str) -> str | None:
    """The document total. Prefer the amount on a 'total'/'amount due' line (excluding
    subtotal/change/cash); otherwise the largest amount in the text."""
    candidates = _total_line_matches(text) or list(_AMOUNT.finditer(text))
    if not candidates:
        return None
    best = max(candidates, key=lambda m: float(m.group(2).replace(",", "")))
    return _amount_str(best)


def find_date(text: str) -> str | None:
    """First date-looking token (ISO or d/m/y with -, / or . separators)."""
    m = _DATE.search(text)
    return m.group(1) if m else None


def apply_backstops(doc_type: str, fields: list[ValidatedField], ocr_text: str) -> None:
    """Fill invoice ``total``/``date`` in place when the LLM left them empty or low-confidence.
    A ``total`` that contradicts an explicit total line (LLM grabbed CASH/CHANGE instead)
    is overridden by that line, regardless of the LLM's confidence."""
    if doc_type != "invoice":
        return

    finders = {"total": find_amount, "date": find_date}
    for vf in fields:
        finder = finders.get(vf.key)
        if finder is None:
            continue
        needs = vf.value == PLACEHOLDER or vf.confidence == "low"
        if not needs:
            continue
        found = finder(ocr_text)
        if found:
            vf.value = found
            vf.confidence = "med"

    for vf in fields:
        if vf.key != "total" or vf.value == PLACEHOLDER:
            continue
        authoritative = find_total_line_amount(ocr_text)
        if authoritative is None:
            continue
        if parse_money(vf.value) != parse_money(authoritative):
            vf.value = authoritative
            vf.confidence = "med"
