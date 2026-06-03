"""Full per-document pipeline: OCR -> classify -> parse -> validate -> derive bbox -> dedupe."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlmodel import Session, select

from ..categories import category_choices, resolve_categories
from ..currency import convert_total_to_eur
from ..models import Document
from ..schema_def import PLACEHOLDER, validate_fields
from ..storage_tree import place
from .backstop import apply_backstops
from .bbox import derive_bbox
from .classify import classify_type
from .duplicate import find_duplicate
from .llm import summarize_doc
from .ocr import run_ocr
from .parse import parse_document_fields

logger = logging.getLogger(__name__)


def process_document(session: Session, doc: Document) -> None:
    start = time.monotonic()

    t = time.monotonic()
    ocr = run_ocr(Path(doc.stored_path), doc.mime)
    ocr_ms = int((time.monotonic() - t) * 1000)
    doc.ocr_text = ocr.text
    doc.page_count = ocr.page_count

    t = time.monotonic()
    doc_type = classify_type(ocr.text)
    classify_ms = int((time.monotonic() - t) * 1000)
    doc.doc_type = doc_type

    t = time.monotonic()
    choices = category_choices(session, doc_type)
    raw = parse_document_fields(doc_type, ocr.text, choices)
    validated = validate_fields(doc_type, raw)
    apply_backstops(doc_type, validated, ocr.text)
    resolve_categories(session, doc_type, validated, raw)

    fields: list[dict] = []
    for vf in validated:
        item = vf.model_dump(exclude_none=True)
        if vf.kind == "value" and vf.value != PLACEHOLDER:
            bbox = derive_bbox(vf.value, ocr.words)
            if bbox:
                item["bbox"] = bbox
        fields.append(item)
    # Convert after bbox derivation so the highlight still points at the original amount.
    convert_total_to_eur(doc_type, fields)
    doc.fields = fields
    extract_ms = int((time.monotonic() - t) * 1000)

    t = time.monotonic()
    doc.summary = summarize_doc(doc_type, fields, ocr.text)
    summary_ms = int((time.monotonic() - t) * 1000)

    doc.stages = [
        {"key": "ocr", "label": "OCR", "ms": ocr_ms},
        {"key": "classify", "label": "Classify", "ms": classify_ms},
        {"key": "extract", "label": "Extract", "ms": extract_ms},
        {"key": "summary", "label": "Summary", "ms": summary_ms},
    ]

    others = session.exec(
        select(Document).where(
            Document.doc_type == doc_type,
            Document.status == "done",
            Document.id != doc.id,
        )
    ).all()
    dup_of = find_duplicate(doc_type, fields, [(o.id, o.fields) for o in others])
    doc.is_dup = dup_of is not None
    doc.dup_of = dup_of

    place(doc)  # move the file into <Type>/<Category>/ on disk

    doc.read_ms = int((time.monotonic() - start) * 1000)
    doc.status = "done"
    doc.error_msg = None
