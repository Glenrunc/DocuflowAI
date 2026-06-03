"""Tests for the agentic RAG module."""

from unittest.mock import patch, MagicMock

from app.pipeline.agent import _parse_action, _build_stats, _tool_aggregate
from app.models import Document


def test_parse_action_json():
    raw = '{"thought": "hmm", "action": "search", "params": {"query": "test"}}'
    result = _parse_action(raw)
    assert result is not None
    assert result["action"] == "search"
    assert result["params"]["query"] == "test"


def test_parse_action_markdown_fence():
    raw = '```json\n{"thought": "ok", "action": "answer", "params": {"text": "done"}}\n```'
    result = _parse_action(raw)
    assert result is not None
    assert result["action"] == "answer"


def test_parse_action_garbage():
    assert _parse_action("not json at all") is None


def test_parse_action_embedded():
    raw = 'Some preamble {"action": "filter", "params": {"type": "invoice"}} trailing'
    result = _parse_action(raw)
    assert result is not None
    assert result["action"] == "filter"


def test_tool_aggregate(session):
    doc = Document(
        filename="inv.pdf",
        mime="application/pdf",
        stored_path="/tmp/inv.pdf",
        doc_type="invoice",
        status="done",
        fields=[
            {"key": "total", "kind": "value", "value": "100.50", "label": "Total"},
            {"key": "taxes", "kind": "value", "value": "20.10", "label": "Taxes"},
        ],
    )
    session.add(doc)
    session.commit()

    result = _tool_aggregate(session, {"type": "invoice", "field": "total", "op": "sum"})
    assert "100.50" in result

    result = _tool_aggregate(session, {"type": "invoice", "field": "total", "op": "count"})
    assert "1" in result


def test_tool_aggregate_no_docs(session):
    result = _tool_aggregate(session, {"type": "contract", "field": "value", "op": "sum"})
    assert "No" in result
