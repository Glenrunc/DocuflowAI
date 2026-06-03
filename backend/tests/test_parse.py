"""parse_fields shape tolerance: wrapped vs bare LLM output (small-model drift)."""

from app.pipeline import llm
from app.pipeline.llm import _coerce_field_map

WRAPPED = {"fields": {"date": {"value": "2026-05-28", "confidence": "high"}}}
BARE = {"date": {"value": "2026-05-28", "confidence": "high"},
        "total": {"value": "CA$32.19", "confidence": "high"}}


def test_coerce_accepts_wrapped():
    assert _coerce_field_map(WRAPPED) == {"date": {"value": "2026-05-28", "confidence": "high"}}


def test_coerce_accepts_bare_map():
    assert _coerce_field_map(BARE) == BARE


def test_coerce_rejects_garbage():
    assert _coerce_field_map({"answer": "nope"}) == {}
    assert _coerce_field_map({}) == {}


def test_parse_fields_recovers_bare_output(monkeypatch):
    monkeypatch.setattr(llm, "_chat_json", lambda *a, **k: BARE)
    out = llm.parse_fields("invoice", "irrelevant text")
    assert out["fields"]["total"]["value"] == "CA$32.19"
