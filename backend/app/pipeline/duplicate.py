"""Duplicate detection by comparing identifying fields (per-type) against already-processed docs.
No embeddings — normalized fuzzy similarity over the schema's `identifying` keys."""

from __future__ import annotations

from rapidfuzz import fuzz

from ..config import settings
from ..schema_def import get_type


def _values(fields: list[dict]) -> dict[str, str]:
    return {f["key"]: (f.get("value") or "").strip().lower() for f in fields}


def similarity(doc_type: str, a: list[dict], b: list[dict]) -> float:
    keys = get_type(doc_type).identifying
    if not keys:
        return 0.0
    va, vb = _values(a), _values(b)
    scores = []
    for k in keys:
        x, y = va.get(k, ""), vb.get(k, "")
        if not x and not y:
            continue
        scores.append(fuzz.ratio(x, y) / 100.0)
    return sum(scores) / len(scores) if scores else 0.0


def find_duplicate(
    doc_type: str, fields: list[dict], existing: list[tuple[str, list[dict]]]
) -> str | None:
    """Return the id of the most similar prior doc if above threshold, else None."""
    best_id, best_score = None, 0.0
    for other_id, other_fields in existing:
        score = similarity(doc_type, fields, other_fields)
        if score > best_score:
            best_id, best_score = other_id, score
    return best_id if best_score >= settings.duplicate_threshold else None
