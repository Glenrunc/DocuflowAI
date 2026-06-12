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


def test_apply_backstops_overrides_total_contradicting_total_line():
    # LLM confidently grabbed the CASH amount — the explicit TOTAL line wins.
    fields = [_vf("total", "RM 50.00", "high")]
    apply_backstops("invoice", fields, RECEIPT)
    assert fields[0].value == "RM 30.90"
    assert fields[0].confidence == "med"


def test_apply_backstops_keeps_llm_total_matching_total_line():
    fields = [_vf("total", "30.90", "high")]
    apply_backstops("invoice", fields, RECEIPT)
    assert fields[0].value == "30.90"
    assert fields[0].confidence == "high"


def test_apply_backstops_keeps_llm_total_when_no_total_line():
    fields = [_vf("total", "12.40", "high")]
    apply_backstops("invoice", fields, "Item A 5.00\nItem B 12.40")
    assert fields[0].value == "12.40"


def test_apply_backstops_noop_for_non_invoice():
    fields = [_vf("total", PLACEHOLDER, "low")]
    apply_backstops("contract", fields, RECEIPT)
    assert fields[0].value == PLACEHOLDER


# Real SROIE receipt shape: LLM picked CASH 70.30, true total on the TOTAL AMT line.
INDAH_RECEIPT = (
    "INDAH GIFT & HOME DECO\n"
    "62483 1 55.90 55.90\n"
    "@DISC 10.00% -5.59\n"
    "#Total Qty 2\n"
    "TOTAL AMT............... RM 60.31\n"
    "ROUNDING ADJ............ -0.01\n"
    "RM 60.30\n"
    "CASH.................... RM 70.30\n"
    "CHANGE.................. RM 10.00"
)


def test_apply_backstops_fixes_cash_grabbed_as_total():
    fields = [_vf("total", "70.30", "high")]
    apply_backstops("invoice", fields, INDAH_RECEIPT)
    assert fields[0].value == "RM 60.31"
