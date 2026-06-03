"""Organize stored files on disk into a real folder tree: <Type>/<Category>/<filename>.

Files land flat at upload (type unknown then); once the pipeline has classified and categorized
a document, ``place`` moves its file into the tree. Changing a document's type or category
re-places it. Empty folders left behind are pruned."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .config import settings
from .models import Document
from .schema_def import get_type


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", name).strip() or "_"


def _type_label(doc_type: str | None) -> str:
    try:
        return get_type(doc_type or "other").label
    except KeyError:
        return "Other"


def _category_label(doc: Document) -> str | None:
    """Human label of the doc's category. None if the type has no category field at all."""
    cat_field = next((f for f in (doc.fields or []) if f.get("kind") == "category"), None)
    if cat_field is None:
        return None
    value = (cat_field.get("value") or "").strip()
    if not value:
        return "Uncategorized"
    opt = next((o for o in (cat_field.get("options") or []) if o.get("value") == value), None)
    return (opt or {}).get("label") or value.replace("_", " ").title()


def _rel_path(doc: Document) -> Path:
    parts = [_safe(_type_label(doc.doc_type))]
    cat = _category_label(doc)
    if cat is not None:
        parts.append(_safe(cat))
    parts.append(_safe(doc.filename))
    return Path(*parts)


def _prune_empty(d: Path) -> None:
    """Remove now-empty folders up to (but never including) the storage root."""
    root = settings.storage_dir.resolve()
    d = d.resolve()
    while d != root and root in d.parents and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def place(doc: Document) -> None:
    """Move the document's file to <storage>/<Type>/<Category>/<filename>, updating
    ``doc.stored_path``. No-op if already there or the source is missing."""
    src = Path(doc.stored_path)
    if not src.exists():
        return
    target = settings.storage_dir / _rel_path(doc)
    if src.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}-{doc.id[:6]}{target.suffix}")
    shutil.move(str(src), str(target))
    doc.stored_path = str(target)
    _prune_empty(src.parent)
