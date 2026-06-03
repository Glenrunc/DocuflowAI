"""Classification: deterministic heuristic + the LLM-'other' guardrail in classify_type.

The LLM call (_chat_json) is monkeypatched so these run without GPU/Ollama."""

from app.pipeline import llm

RECEIPT = "INDAH GIFT & HOME DECO\nRECEIPT\nQTY PRICE\nTOTAL RM 50.00\nChange Due RM 34.10"
CONTRACT = "SERVICE AGREEMENT\nThis contract is between Party A and Party B who hereby agree to the terms."


def test_heuristic_maps_receipt_to_invoice():
    assert llm._heuristic_type(RECEIPT) == "invoice"


def test_heuristic_detects_contract():
    assert llm._heuristic_type(CONTRACT) == "contract"


def test_heuristic_returns_none_below_threshold():
    assert llm._heuristic_type("Just some unrelated prose with no signals.") is None


def test_classify_overrides_llm_other_with_heuristic(monkeypatch):
    monkeypatch.setattr(llm, "_chat_json", lambda *a, **k: {"type": "other"})
    assert llm.classify_type(RECEIPT) == "invoice"


def test_classify_keeps_concrete_llm_verdict(monkeypatch):
    monkeypatch.setattr(llm, "_chat_json", lambda *a, **k: {"type": "contract"})
    assert llm.classify_type(RECEIPT) == "contract"


def test_classify_falls_back_to_other_when_no_signals(monkeypatch):
    monkeypatch.setattr(llm, "_chat_json", lambda *a, **k: {"type": "other"})
    assert llm.classify_type("Unrelated prose with nothing to latch onto.") == "other"
