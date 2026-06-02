"""Duplicate detection over identifying fields (pipeline.duplicate)."""

from app.pipeline.duplicate import find_duplicate, similarity


def _invoice(merchant, total, date):
    return [
        {"key": "merchant", "value": merchant, "kind": "value"},
        {"key": "total", "value": total, "kind": "value"},
        {"key": "date", "value": date, "kind": "value"},
    ]


def test_identical_fields_high_similarity():
    a = _invoice("Café Urbain", "$47.85", "2024-11-03")
    b = _invoice("Café Urbain", "$47.85", "2024-11-03")
    assert similarity("invoice", a, b) > 0.95


def test_different_merchants_low_similarity():
    a = _invoice("Café Urbain", "$47.85", "2024-11-03")
    b = _invoice("Hardware Depot", "$1200.00", "2023-01-01")
    assert similarity("invoice", a, b) < 0.85


def test_find_duplicate_returns_match_id():
    new = _invoice("Café Urbain", "$47.85", "2024-11-03")
    existing = [
        ("id-other", _invoice("Hardware Depot", "$1200", "2023-01-01")),
        ("id-dup", _invoice("Café Urbain", "$47.85", "2024-11-03")),
    ]
    assert find_duplicate("invoice", new, existing) == "id-dup"


def test_no_duplicate_below_threshold():
    new = _invoice("Café Urbain", "$47.85", "2024-11-03")
    existing = [("id-other", _invoice("Hardware Depot", "$1200", "2023-01-01"))]
    assert find_duplicate("invoice", new, existing) is None


def test_type_without_identifying_keys_never_duplicates():
    fields = [{"key": "x", "value": "y", "kind": "value"}]
    assert similarity("other", fields, fields) == 0.0
    assert find_duplicate("other", fields, [("id", fields)]) is None
