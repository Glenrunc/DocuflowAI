"""Currency normalization: detection + EUR conversion of invoice totals."""

from app.currency import convert_total_to_eur, detect_currency, to_eur
from app.schema_def import PLACEHOLDER


def test_detect_currency():
    assert detect_currency("CA$32.19") == "CAD"
    assert detect_currency("$ 32.19") == "USD"
    assert detect_currency("RM 50.00") == "MYR"
    assert detect_currency("€21,90") == "EUR"
    assert detect_currency("no currency") is None


def test_to_eur_cad():
    # 32.19 CAD * 0.68 = 21.8892 → "21,89 €"
    assert to_eur("CA$32.19") == "21,89 €"


def _total(value):
    return {"key": "total", "label": "Total", "icon": "💰", "kind": "value", "value": value, "confidence": "high"}


def test_convert_rewrites_cad_total():
    fields = [_total("CA$32.19")]
    convert_total_to_eur("invoice", fields)
    assert fields[0]["value"] == "21,89 €"


def test_convert_leaves_eur_untouched():
    fields = [_total("21,90 €")]
    convert_total_to_eur("invoice", fields)
    assert fields[0]["value"] == "21,90 €"


def test_convert_skips_placeholder():
    fields = [_total(PLACEHOLDER)]
    convert_total_to_eur("invoice", fields)
    assert fields[0]["value"] == PLACEHOLDER


def test_convert_noop_for_non_invoice():
    fields = [_total("CA$32.19")]
    convert_total_to_eur("contract", fields)
    assert fields[0]["value"] == "CA$32.19"
