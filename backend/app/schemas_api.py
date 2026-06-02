from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .models import Document, QAEntry


class FieldOut(BaseModel):
    key: str
    label: str
    icon: str
    kind: str
    value: str
    confidence: str
    bbox: list[float] | None = None
    options: list[dict] | None = None
    edited: bool | None = None


class QAOut(BaseModel):
    question: str
    answer: str
    citation: str | None = None


class DocumentSummary(BaseModel):
    id: str
    filename: str
    type: str | None
    status: str
    isDup: bool
    pageCount: int


class DocumentDetail(DocumentSummary):
    mime: str
    errorMsg: str | None = None
    readMs: int | None = None
    ocrText: str | None = None
    fields: list[FieldOut]
    stages: list[dict]
    qa: list[QAOut]


class EditFieldIn(BaseModel):
    value: str


class SetCategoryIn(BaseModel):
    value: str


class ChangeTypeIn(BaseModel):
    type: str


class QAIn(BaseModel):
    question: str


class DupResolveIn(BaseModel):
    action: Literal["keep_both", "mark_duplicate"]


def to_summary(doc: Document) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        type=doc.doc_type,
        status=doc.status,
        isDup=doc.is_dup,
        pageCount=doc.page_count,
    )


def to_detail(doc: Document, qa: list[QAEntry]) -> DocumentDetail:
    return DocumentDetail(
        **to_summary(doc).model_dump(),
        mime=doc.mime,
        errorMsg=doc.error_msg,
        readMs=doc.read_ms,
        ocrText=doc.ocr_text,
        fields=[FieldOut(**f) for f in (doc.fields or [])],
        stages=list(doc.stages or []),
        qa=[QAOut(question=q.question, answer=q.answer, citation=q.citation) for q in qa],
    )
