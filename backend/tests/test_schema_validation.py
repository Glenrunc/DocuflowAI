"""Validation of raw LLM output against the detected type's schema (schema_def.validate_fields)."""

from app.schema_def import PLACEHOLDER, validate_fields


def test_well_formed_invoice_fields_pass_through():
    raw = {
        "date": {"value": "2024-11-03", "confidence": "high"},
        "merchant": {"value": "Café Urbain", "confidence": "med"},
        "total": {"value": "$47.85", "confidence": "high"},
    }
    out = {f.key: f for f in validate_fields("invoice", raw)}
    assert out["date"].value == "2024-11-03"
    assert out["date"].confidence == "high"
    assert out["merchant"].confidence == "med"


def test_missing_value_falls_back_to_placeholder_low():
    out = {f.key: f for f in validate_fields("invoice", {})}
    assert out["total"].value == PLACEHOLDER
    assert out["total"].confidence == "low"


def test_bad_confidence_coerced_to_low():
    raw = {"total": {"value": "$10", "confidence": "banana"}}
    out = {f.key: f for f in validate_fields("invoice", raw)}
    assert out["total"].confidence == "low"


def test_category_rejects_value_outside_options():
    raw = {"category": {"value": "not_a_category"}}
    out = {f.key: f for f in validate_fields("invoice", raw)}
    assert out["category"].kind == "category"
    assert out["category"].value == ""  # Uncategorized


def test_category_accepts_schema_option():
    opt = next(f for f in validate_fields("invoice", {}) if f.key == "category").options[0].value
    out = {f.key: f for f in validate_fields("invoice", {"category": {"value": opt}})}
    assert out["category"].value == opt


def test_dynamic_type_accepts_arbitrary_keys():
    raw = {"reference_no": {"value": "ABC-1", "confidence": "high"}}
    out = validate_fields("other", raw)
    assert len(out) == 1
    assert out[0].key == "reference_no"
    assert out[0].label == "Reference No"
    assert out[0].value == "ABC-1"


def test_all_schema_fields_emitted_even_when_absent():
    out = validate_fields("contract", {})
    keys = {f.key for f in out}
    assert keys == {"partyA", "partyB", "startDate", "endDate", "value", "contractType"}
