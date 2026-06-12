"""Normalize invoice totals to EUR.

Amounts come in whatever currency the receipt used (CA$, $, RM…). The app reports spend in
euros, so the invoice ``total`` is converted at fixed reference rates. Rates are static
(offline, no FX API) and approximate — good enough for reporting, not accounting-grade."""

from __future__ import annotations

import re

from .schema_def import PLACEHOLDER
from .summary_calc import parse_money

# EUR per 1 unit of currency (static reference rates).
_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.92,
    "CAD": 0.68,
    "GBP": 1.17,
    "CHF": 1.04,
    "AUD": 0.60,
    "NZD": 0.56,
    "JPY": 0.0061,
    "MYR": 0.20,
    "SGD": 0.68,
}

# Checked longest-first so 'CA$' wins over '$', and 'CAD' over bare codes.
_SYMBOLS = [
    ("CA$", "CAD"), ("C$", "CAD"), ("US$", "USD"), ("A$", "AUD"), ("NZ$", "NZD"),
    ("S$", "SGD"), ("RM", "MYR"), ("CHF", "CHF"), ("€", "EUR"), ("£", "GBP"),
    ("¥", "JPY"), ("$", "USD"),
]


def detect_currency(value: str) -> str | None:
    """Currency code from an amount string. Explicit 3-letter codes win, then symbols."""
    up = (value or "").upper()
    for code in _TO_EUR:
        if code in up:
            return code
    for sym, code in _SYMBOLS:
        if sym.upper() in up:
            return code
    return None


def _format_eur(eur: float) -> str:
    return f"{eur:.2f}".replace(".", ",") + " €"


def infer_doc_currency(text: str) -> str | None:
    """Dominant currency of a document from its OCR text (most frequent symbol/code).
    Fallback for amounts extracted without a symbol (e.g. SROIE receipts: 'RM' is on
    the price lines but not in the extracted total)."""
    up = text or ""
    counts: dict[str, int] = {}
    for token, code in [(c, c) for c in _TO_EUR] + _SYMBOLS:
        pat = rf"\b{token}\b" if token.isalpha() else re.escape(token)
        n = len(re.findall(pat, up, re.IGNORECASE))
        if n:
            counts[code] = counts.get(code, 0) + n
            up = re.sub(pat, " ", up, flags=re.IGNORECASE)  # 'CA$' must not also count as '$'
    if not counts:
        return None
    return max(counts, key=lambda c: counts[c])


def to_eur(value: str) -> str | None:
    """Convert an amount string to a formatted EUR string, or None if not convertible."""
    cur = detect_currency(value)
    amt = parse_money(value)
    if cur is None or amt is None or cur not in _TO_EUR:
        return None
    return _format_eur(amt * _TO_EUR[cur])


# Money fields per document type — only these get rewritten in EUR.
_MONEY_FIELDS = {"invoice": {"total", "taxes"}, "contract": {"value"}}


def convert_money_fields_to_eur(doc_type: str, fields: list[dict], ocr_text: str = "") -> None:
    """Rewrite money fields in EUR (in place). Called after bbox derivation so the
    highlight keeps pointing at the original amount. Amounts without a symbol fall back
    to the document's dominant currency (from OCR text). No-op if already EUR."""
    keys = _MONEY_FIELDS.get(doc_type)
    if not keys:
        return
    doc_currency: str | None = None
    for f in fields:
        value = f.get("value")
        if f.get("key") not in keys or value in (None, "", PLACEHOLDER):
            continue
        if "%" in value:  # a rate (e.g. 'GST 6%'), not an amount
            continue
        explicit = detect_currency(value)
        cur = explicit
        if cur is None:
            if doc_currency is None:
                doc_currency = infer_doc_currency(ocr_text) or "?"
            cur = doc_currency if doc_currency != "?" else None
        if cur is None or cur not in _TO_EUR:
            continue
        amt = parse_money(value)
        if amt is None:
            continue
        if cur == "EUR":
            if explicit is None:  # bare number in a EUR document — uniform formatting
                f["value"] = _format_eur(amt)
            continue
        f["value"] = _format_eur(amt * _TO_EUR[cur])
