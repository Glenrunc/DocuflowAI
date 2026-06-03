"""End-to-end pipeline orchestration on SQLite, with OCR + Ollama mocked.

Exercises process_document: OCR -> classify -> parse -> validate -> derive bbox -> dedupe -> done.
The GPU/Ollama-dependent steps are monkeypatched; a real-stack variant is out of scope here
(see README "Verification end-to-end")."""

import pytest

from app.models import Document
from app.pipeline import run as run_mod
from app.pipeline.ocr import OcrResult, OcrWord

OCR_TEXT = "Café Urbain\nTotal due: $47.85\nDate 2024-11-03"


def _fake_ocr(*_args, **_kwargs):
    return OcrResult(
        text=OCR_TEXT,
        words=[
            OcrWord(text="Café", bbox=[10.0, 8.0, 9.0, 4.0], page=0),
            OcrWord(text="Urbain", bbox=[20.0, 8.0, 9.0, 4.0], page=0),
            OcrWord(text="$47.85", bbox=[64.0, 72.0, 12.0, 4.0], page=0),
        ],
        page_count=1,
    )


def _fake_parse(_doc_type, _ocr_text, _category_choices=None):
    return {
        "merchant": {"value": "Café Urbain", "confidence": "high"},
        "total": {"value": "$47.85", "confidence": "high"},
        "date": {"value": "2024-11-03", "confidence": "high"},
    }


@pytest.fixture(autouse=True)
def _patch_pipeline(monkeypatch):
    monkeypatch.setattr(run_mod, "run_ocr", _fake_ocr)
    monkeypatch.setattr(run_mod, "classify_type", lambda _t: "invoice")
    monkeypatch.setattr(run_mod, "parse_document_fields", _fake_parse)
    monkeypatch.setattr(run_mod, "embed_document", lambda *_a, **_k: None)


def _new_doc(session) -> Document:
    doc = Document(filename="receipt.pdf", mime="application/pdf", stored_path="/tmp/receipt.pdf")
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_pipeline_processes_to_done_with_fields_and_bbox(session):
    doc = _new_doc(session)
    run_mod.process_document(session, doc)

    assert doc.status == "done"
    assert doc.doc_type == "invoice"
    assert doc.ocr_text == OCR_TEXT
    assert doc.page_count == 1
    assert doc.read_ms is not None

    by_key = {f["key"]: f for f in doc.fields}
    assert by_key["merchant"]["value"] == "Café Urbain"
    assert by_key["merchant"]["bbox"] == [10.0, 8.0, 19.0, 4.0]
    assert by_key["total"]["bbox"] == [64.0, 72.0, 12.0, 4.0]
    assert not doc.is_dup


def test_pipeline_flags_duplicate_against_prior_done_doc(session):
    first = _new_doc(session)
    run_mod.process_document(session, first)
    session.add(first)
    session.commit()

    second = _new_doc(session)
    run_mod.process_document(session, second)

    assert second.is_dup is True
    assert second.dup_of == first.id
