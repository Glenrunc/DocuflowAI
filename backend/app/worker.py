"""Single background worker. Claims queued jobs (FOR UPDATE SKIP LOCKED) and runs the pipeline.

One worker instance naturally serializes GPU work (docTR + Ollama share ~6GB VRAM)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlmodel import Session, select

from .config import settings
from .db import engine, init_db
from .models import Document, Job
from .pipeline import llm, ocr
from .pipeline.run import process_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")

FRIENDLY_ERROR = "We couldn't read this document — please try a clearer file."


def _claim(session: Session) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.exec(stmt).first()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    return job


def _recover_orphans() -> None:
    """Re-queue work interrupted by a worker crash/restart: a job left in ``running``
    (and its document in ``processing``) will otherwise never be picked up again."""
    with Session(engine) as session:
        jobs = session.exec(select(Job).where(Job.status == "running")).all()
        for job in jobs:
            job.status = "queued"
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            doc = session.get(Document, job.doc_id)
            if doc is not None and doc.status == "processing":
                doc.status = "queued"
                session.add(doc)
        if jobs:
            logger.info("recovered %d orphaned job(s)", len(jobs))
        session.commit()


def process_one() -> bool:
    """Claim and process a single job. Returns True if work was done."""
    with Session(engine) as session:
        job = _claim(session)
        if job is None:
            session.rollback()
            return False
        doc = session.get(Document, job.doc_id)
        if doc is not None:
            doc.status = "processing"
            session.add(doc)
        session.commit()
        if doc is None:
            job.status = "error"
            session.add(job)
            session.commit()
            return True

        try:
            process_document(session, doc)
            job.status = "done"
        except Exception:  # noqa: BLE001 — any pipeline failure becomes a friendly error state
            logger.exception("pipeline failed for doc %s", doc.id)
            session.rollback()
            doc = session.get(Document, job.doc_id)
            if doc is not None:
                doc.status = "error"
                doc.error_msg = FRIENDLY_ERROR
                session.add(doc)
            job.status = "error"
            job.updated_at = datetime.now(timezone.utc)
        else:
            session.add(doc)
        session.add(job)
        session.commit()
        return True


def main() -> None:
    init_db()
    _recover_orphans()
    logger.info("worker started (model=%s, ocr_device=%s)", settings.ollama_model, settings.ocr_device)
    t = time.monotonic()
    try:
        ocr.warmup()
        llm.warmup()
        logger.info("warmup done in %.1fs", time.monotonic() - t)
    except Exception:  # noqa: BLE001 — warmup is best-effort; first doc just pays cold load
        logger.exception("warmup failed (continuing)")
    while True:
        try:
            did_work = process_one()
        except Exception:  # noqa: BLE001
            logger.exception("worker loop error")
            did_work = False
        if not did_work:
            time.sleep(settings.worker_poll_interval)


if __name__ == "__main__":
    main()
