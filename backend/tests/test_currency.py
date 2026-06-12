"""Currency normalization: detection + EUR conversion of invoice totals."""

from app.currency import convert_money_fields_to_eur, detect_currency, to_eur
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
    convert_money_fields_to_eur("invoice", fields)
    assert fields[0]["value"] == "21,89 €"


def test_convert_leaves_eur_untouched():
    fields = [_total("21,90 €")]
    convert_money_fields_to_eur("invoice", fields)
    assert fields[0]["value"] == "21,90 €"


def test_convert_skips_placeholder():
    fields = [_total(PLACEHOLDER)]
    convert_money_fields_to_eur("invoice", fields)
    assert fields[0]["value"] == PLACEHOLDER


def test_convert_noop_for_non_invoice():
    fields = [_total("CA$32.19")]
    convert_money_fields_to_eur("contract", fields)
    assert fields[0]["value"] == "CA$32.19"


def test_convert_rewrites_invoice_taxes_and_total():
    fields = [
        _total("RM 50.00"),
        {"key": "taxes", "label": "Taxes", "kind": "value", "value": "RM 3.00", "confidence": "high"},
    ]
    convert_money_fields_to_eur("invoice", fields)
    assert fields[0]["value"] == "10,00 €"
    assert fields[1]["value"] == "0,60 €"


def test_convert_rewrites_contract_value():
    fields = [{"key": "value", "label": "Value", "kind": "value", "value": "$1000.00", "confidence": "high"}]
    convert_money_fields_to_eur("contract", fields)
    assert fields[0]["value"] == "920,00 €"


def test_bare_amount_uses_doc_currency_from_ocr():
    fields = [_total("50.00")]
    convert_money_fields_to_eur("invoice", fields, "MR D.I.Y.\nITEM RM 2.00\nTOTAL RM 50.00\nGST")
    assert fields[0]["value"] == "10,00 €"


def test_bare_amount_without_any_currency_stays():
    fields = [_total("50.00")]
    convert_money_fields_to_eur("invoice", fields, "no currency anywhere")
    assert fields[0]["value"] == "50.00"


def test_percentage_value_not_converted():
    fields = [{"key": "taxes", "label": "Taxes", "kind": "value", "value": "SR GST 6%", "confidence": "low"}]
    convert_money_fields_to_eur("invoice", fields, "TOTAL RM 343.95")
    assert fields[0]["value"] == "SR GST 6%"
