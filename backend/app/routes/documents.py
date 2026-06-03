from __future__ import annotations

import mimetypes
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlmodel import Session, delete, select

from ..config import settings
from ..db import get_session
from ..models import Chunk, Document, Job, QAEntry
from ..schema_def import PLACEHOLDER, get_type, validate_fields
from ..storage_tree import place
from ..schemas_api import (
    ChangeTypeIn,
    DocumentDetail,
    DocumentSummary,
    DupResolveIn,
    EditFieldIn,
    SetCategoryIn,
    to_detail,
    to_summary,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_SUFFIX = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif"}


def _default_fields(doc_type: str) -> list[dict]:
    return [vf.model_dump(exclude_none=True) for vf in validate_fields(doc_type, {})]


def _get_doc(session: Session, doc_id: str) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("", response_model=list[DocumentSummary])
async def upload(files: list[UploadFile], session: Session = Depends(get_session)):
    out: list[DocumentSummary] = []
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIX:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
        stored = settings.storage_dir / f"{uuid4().hex}{suffix}"
        stored.write_bytes(await f.read())
        mime = f.content_type or mimetypes.guess_type(str(stored))[0] or "application/octet-stream"

        doc = Document(filename=f.filename or stored.name, mime=mime, stored_path=str(stored))
        session.add(doc)
        session.flush()
        session.add(Job(doc_id=doc.id))
        out.append(to_summary(doc))
    session.commit()
    return out


@router.get("", response_model=list[DocumentSummary])
def list_documents(session: Session = Depends(get_session)):
    docs = session.exec(select(Document).order_by(Document.created_at)).all()
    return [to_summary(d) for d in docs]


@router.get("/search", response_model=list[DocumentSummary])
def search_documents(q: str = "", session: Session = Depends(get_session)):
    """Full-text search over OCR text + filename. Ranked by ts_rank; ILIKE fallback for
    short/partial terms that plainto_tsquery can't match."""
    q = q.strip()
    if not q:
        return []
    fts = text(
        "SELECT id FROM document "
        "WHERE to_tsvector('french', coalesce(ocr_text,'') || ' ' || filename) "
        "@@ plainto_tsquery('french', :q) "
        "ORDER BY ts_rank(to_tsvector('french', coalesce(ocr_text,'') || ' ' || filename), "
        "plainto_tsquery('french', :q)) DESC"
    )
    ids = [row[0] for row in session.execute(fts, {"q": q}).all()]
    if not ids:
        like = text(
            "SELECT id FROM document WHERE filename ILIKE :p OR ocr_text ILIKE :p "
            "ORDER BY created_at DESC"
        )
        ids = [row[0] for row in session.execute(like, {"p": f"%{q}%"}).all()]
    docs = {d.id: d for d in session.exec(select(Document).where(Document.id.in_(ids)))}
    return [to_summary(docs[i]) for i in ids if i in docs]


@router.get("/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: str, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    qa = session.exec(
        select(QAEntry).where(QAEntry.doc_id == doc_id).order_by(QAEntry.created_at)
    ).all()
    return to_detail(doc, qa)


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    Path(doc.stored_path).unlink(missing_ok=True)
    (settings.storage_dir / f"{doc.id}_p1.png").unlink(missing_ok=True)
    session.exec(delete(QAEntry).where(QAEntry.doc_id == doc_id))
    session.exec(delete(Job).where(Job.doc_id == doc_id))
    session.exec(delete(Chunk).where(Chunk.doc_id == doc_id))
    session.delete(doc)
    session.commit()


@router.get("/{doc_id}/file")
def get_file(doc_id: str, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    path = Path(doc.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        media_type=doc.mime,
        content_disposition_type="inline",
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.get("/{doc_id}/preview")
def get_preview(doc_id: str, session: Session = Depends(get_session)):
    """Page-1 raster for display. For PDFs, render (and cache) a PNG so the bbox overlay
    aligns exactly; for images, serve the original file."""
    doc = _get_doc(session, doc_id)
    path = Path(doc.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if doc.mime != "application/pdf":
        return FileResponse(path, media_type=doc.mime, content_disposition_type="inline")
    cache = settings.storage_dir / f"{doc.id}_p1.png"
    if not cache.exists():
        from ..pipeline.ocr import render_page1_png

        render_page1_png(path, doc.mime, cache)
    return FileResponse(cache, media_type="image/png", content_disposition_type="inline")


@router.get("/{doc_id}/status")
def get_status(doc_id: str, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    return {"status": doc.status, "errorMsg": doc.error_msg}


@router.patch("/{doc_id}/type", response_model=DocumentDetail)
def change_type(doc_id: str, body: ChangeTypeIn, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    try:
        get_type(body.type)
    except KeyError:
        raise HTTPException(status_code=400, detail="Unknown document type")
    doc.doc_type = body.type
    doc.fields = _default_fields(body.type)
    doc.is_dup = False
    place(doc)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return to_detail(doc, [])


@router.patch("/{doc_id}/fields/{key}", response_model=DocumentDetail)
def edit_field(doc_id: str, key: str, body: EditFieldIn, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    fields = list(doc.fields or [])
    found = False
    for f in fields:
        if f["key"] == key:
            f["value"] = body.value
            f["confidence"] = "high"
            f["edited"] = True
            found = True
    if not found:
        raise HTTPException(status_code=404, detail="Field not found")
    doc.fields = fields
    session.add(doc)
    session.commit()
    qa = session.exec(select(QAEntry).where(QAEntry.doc_id == doc_id)).all()
    session.refresh(doc)
    return to_detail(doc, qa)


@router.patch("/{doc_id}/category", response_model=DocumentDetail)
def set_category(doc_id: str, body: SetCategoryIn, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    fields = list(doc.fields or [])
    for f in fields:
        if f.get("kind") == "category":
            f["value"] = body.value
    doc.fields = fields
    place(doc)
    session.add(doc)
    session.commit()
    qa = session.exec(select(QAEntry).where(QAEntry.doc_id == doc_id)).all()
    session.refresh(doc)
    return to_detail(doc, qa)


@router.post("/{doc_id}/duplicate", response_model=DocumentSummary)
def resolve_duplicate(doc_id: str, body: DupResolveIn, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    doc.is_dup = False  # both actions dismiss the banner (§8/§12.6)
    if body.action == "keep_both":
        doc.dup_of = None
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return to_summary(doc)
