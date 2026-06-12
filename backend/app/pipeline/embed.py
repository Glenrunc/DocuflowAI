"""Embedding via Ollama + chunk storage for the agentic RAG vector store."""

from __future__ import annotations

import logging
import math

from sqlalchemy import text
from sqlmodel import Session, delete, select

from ..config import settings
from ..models import Chunk, Document
from .llm import client

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _chunk_text(text: str, page_count: int) -> list[dict]:
    """Split text into overlapping chunks. If the document has page breaks (form-feed or
    multiple pages from OCR), chunk per page; otherwise use fixed-size windows."""
    pages = text.split("\f") if "\f" in text else [text]
    if len(pages) == 1 and page_count > 1:
        lines = text.splitlines()
        lines_per_page = max(1, len(lines) // page_count)
        pages = [
            "\n".join(lines[i : i + lines_per_page])
            for i in range(0, len(lines), lines_per_page)
        ]

    chunks: list[dict] = []
    for page_idx, page_text in enumerate(pages):
        page_text = page_text.strip()
        if not page_text:
            continue
        words = page_text.split()
        if len(words) <= CHUNK_SIZE:
            chunks.append({"page": page_idx, "content": page_text})
        else:
            step = CHUNK_SIZE - CHUNK_OVERLAP
            for i in range(0, len(words), step):
                chunk_words = words[i : i + CHUNK_SIZE]
                if len(chunk_words) < CHUNK_OVERLAP and chunks:
                    break
                chunks.append({"page": page_idx, "content": " ".join(chunk_words)})
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Call Ollama embed endpoint for a batch of texts."""
    if not texts:
        return []
    resp = client().embed(model=settings.ollama_embed_model, input=texts)
    return resp["embeddings"]


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text])[0]


def embed_document(session: Session, doc: Document) -> None:
    """Chunk, embed, and store vectors for a processed document."""
    if not doc.ocr_text:
        return

    session.exec(delete(Chunk).where(Chunk.doc_id == doc.id))

    raw_chunks = _chunk_text(doc.ocr_text, doc.page_count)
    if not raw_chunks:
        return

    texts = [c["content"] for c in raw_chunks]
    try:
        vectors = embed_texts(texts)
    except Exception:
        logger.exception("embedding failed for doc %s — skipping", doc.id)
        return

    for chunk_meta, vector in zip(raw_chunks, vectors):
        session.add(
            Chunk(
                doc_id=doc.id,
                page=chunk_meta["page"],
                content=chunk_meta["content"],
                embedding=vector,
            )
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _chunk_result(c: Chunk, score: float, key: str = "score") -> dict:
    return {"doc_id": c.doc_id, "page": c.page, "content": c.content, key: score}


def search_vectors(session: Session, query_vec: list[float], top_k: int) -> list[dict]:
    """Cosine similarity over all stored chunk embeddings."""
    chunks = session.exec(select(Chunk)).all()
    scored = [
        _chunk_result(c, cosine_similarity(query_vec, c.embedding))
        for c in chunks
        if c.embedding
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]


def search_bm25(session: Session, query: str, top_k: int) -> list[dict]:
    """Keyword search over chunk content via Postgres full-text search."""
    fts = text(
        "SELECT id FROM chunk "
        "WHERE to_tsvector('french', content) @@ plainto_tsquery('french', :q) "
        "ORDER BY ts_rank(to_tsvector('french', content), plainto_tsquery('french', :q)) DESC "
        "LIMIT :k"
    )
    rows = session.execute(fts, {"q": query, "k": top_k}).all()
    out = []
    for rank, (chunk_id,) in enumerate(rows):
        c = session.get(Chunk, chunk_id)
        if c:
            out.append(_chunk_result(c, 1.0 / (rank + 1)))
    return out


def hybrid_search(session: Session, query: str, query_vec: list[float], top_k: int) -> list[dict]:
    """Reciprocal-rank fusion of vector and keyword search results."""
    k_rrf = 60  # standard RRF damping constant
    fused: dict[tuple, dict] = {}
    for results in (search_vectors(session, query_vec, top_k), search_bm25(session, query, top_k)):
        for rank, r in enumerate(results):
            key = (r["doc_id"], r["page"], r["content"])
            entry = fused.setdefault(
                key, {"doc_id": r["doc_id"], "page": r["page"], "content": r["content"], "rrf_score": 0.0}
            )
            entry["rrf_score"] += 1.0 / (k_rrf + rank + 1)
    ranked = sorted(fused.values(), key=lambda r: r["rrf_score"], reverse=True)
    return ranked[:top_k]
