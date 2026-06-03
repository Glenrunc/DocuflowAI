"""Deterministic invoice backstop: amount/date regex + apply_backstops repair rules."""

from app.pipeline.backstop import apply_backstops, find_amount, find_date
from app.schema_def import PLACEHOLDER, ValidatedField

RECEIPT = "MR D.I.Y\nQTY PRICE\nSUBTOTAL RM 28.20\nTOTAL RM 30.90\nCASH RM 50.00\nCHANGE RM 19.10"


def test_find_amount_prefers_total_over_change_and_subtotal():
    assert find_amount(RECEIPT) == "RM 30.90"


def test_find_amount_falls_back_to_largest_when_no_total_line():
    assert find_amount("Item A 5.00\nItem B 12.40\nItem C 3.00") == "12.40"


def test_find_amount_none_when_no_amount():
    assert find_amount("no numbers with cents here") is None


def test_find_date_iso_and_dmy():
    assert find_date("Invoice 18-11-18 paid") == "18-11-18"
    assert find_date("Date: 2018-11-18") == "2018-11-18"


def _vf(key, value, confidence):
    return ValidatedField(key=key, label=key.title(), icon="x", kind="value", value=value, confidence=confidence)


def test_apply_backstops_fills_missing_total():
    fields = [_vf("total", PLACEHOLDER, "low"), _vf("date", PLACEHOLDER, "low")]
    apply_backstops("invoice", fields, RECEIPT)
    by_key = {f.key: f for f in fields}
    assert by_key["total"].value == "RM 30.90"
    assert by_key["total"].confidence == "med"


def test_apply_backstops_keeps_confident_llm_value():
    fields = [_vf("total", "RM 99.00", "high")]
    apply_backstops("invoice", fields, RECEIPT)
    assert fields[0].value == "RM 99.00"


def test_apply_backstops_noop_for_non_invoice():
    fields = [_vf("total", PLACEHOLDER, "low")]
    apply_backstops("contract", fields, RECEIPT)
    assert fields[0].value == PLACEHOLDER
