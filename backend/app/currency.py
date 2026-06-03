"""Normalize invoice totals to EUR.

Amounts come in whatever currency the receipt used (CA$, $, RM…). The app reports spend in
euros, so the invoice ``total`` is converted at fixed reference rates. Rates are static
(offline, no FX API) and approximate — good enough for reporting, not accounting-grade."""

from __future__ import annotations

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


def to_eur(value: str) -> str | None:
    """Convert an amount string to a formatted EUR string, or None if not convertible."""
    cur = detect_currency(value)
    amt = parse_money(value)
    if cur is None or amt is None or cur not in _TO_EUR:
        return None
    return _format_eur(amt * _TO_EUR[cur])


def convert_total_to_eur(doc_type: str, fields: list[dict]) -> None:
    """Rewrite the invoice ``total`` in EUR (in place). Called after bbox derivation so the
    highlight keeps pointing at the original amount. No-op if empty or already EUR."""
    if doc_type != "invoice":
        return
    for f in fields:
        value = f.get("value")
        if f.get("key") != "total" or value in (None, "", PLACEHOLDER):
            continue
        if detect_currency(value) == "EUR":
            return
        eur = to_eur(value)
        if eur:
            f["value"] = eur
