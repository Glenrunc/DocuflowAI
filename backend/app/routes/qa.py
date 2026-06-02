from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..db import get_session
from ..models import Document, QAEntry
from ..pipeline.citation import build_citation
from ..pipeline.llm import answer_question
from ..schemas_api import QAIn, QAOut

router = APIRouter(prefix="/api/documents", tags=["qa"])


@router.post("/{doc_id}/qa", response_model=QAOut)
def ask(doc_id: str, body: QAIn, session: Session = Depends(get_session)):
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != "done" or not doc.ocr_text:
        raise HTTPException(status_code=409, detail="This document isn't ready yet.")

    result = answer_question(doc.ocr_text, doc.fields or [], body.question)
    citation = build_citation(doc.ocr_text, result["source"])

    entry = QAEntry(doc_id=doc_id, question=body.question, answer=result["answer"], citation=citation)
    session.add(entry)
    session.commit()
    return QAOut(question=body.question, answer=result["answer"], citation=citation)
