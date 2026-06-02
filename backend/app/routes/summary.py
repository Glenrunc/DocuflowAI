import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlmodel import Session, select

from ..csv_export import export_flat, export_invoice
from ..db import get_session
from ..models import Document
from ..pipeline.llm import stream_corpus
from ..schemas_api import QAIn
from ..summary_calc import build_corpus, build_summary

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    docs = session.exec(select(Document).order_by(Document.created_at)).all()
    return build_summary(docs)


@router.post("/qa")
def ask_all(body: QAIn, session: Session = Depends(get_session)):
    """Stream the global Q&A as NDJSON: {type:thinking|answer, text} chunks, then {type:done}."""
    docs = session.exec(select(Document).order_by(Document.created_at)).all()
    done = [d for d in docs if d.status == "done"]

    def gen():
        if not done:
            yield json.dumps({"type": "answer", "text": "No processed documents yet."}) + "\n"
            yield json.dumps({"type": "done", "citation": None}) + "\n"
            return
        corpus = build_corpus(docs)
        for part in stream_corpus(body.question, corpus):
            yield json.dumps(part, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done", "citation": f"{len(done)} documents"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.get("/export.csv")
def export_csv(profile: str = "flat", session: Session = Depends(get_session)):
    docs = session.exec(
        select(Document).where(Document.status == "done").order_by(Document.created_at)
    ).all()
    body = export_invoice(docs) if profile == "invoice" else export_flat(docs)
    filename = f"docuflow-{profile}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
