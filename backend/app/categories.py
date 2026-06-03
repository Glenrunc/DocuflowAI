"""Discovered-but-stable categories.

The schema seeds a fixed set of category options per type, but the LLM may propose new ones.
To keep this from drifting (Food/Meals/Restaurant…), discovery is anchored: the parser is shown
the categories already known (schema seeds + everything seen in the DB) and asked to reuse one
before inventing a new one. New labels are slugified and reused by later documents.

Pure-ish helpers; the only side input is the DB session (read-only here)."""

from __future__ import annotations

import hashlib
import re

from sqlmodel import Session, select

from .models import Document
from .schema_def import CategoryOption, ValidatedField, get_type

# Colors for discovered categories (schema seeds keep their own). Deterministic pick by slug.
_CAT_PALETTE = [
    "#F97316", "#0EA5E9", "#64748B", "#A855F7", "#14B8A6",
    "#EF4444", "#EAB308", "#6366F1", "#EC4899", "#84CC16",
]


def slugify(label: str | None) -> str:
    """Lowercase, trim, non-alphanumerics → single underscore. '' for falsy input."""
    s = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    return s


def _label(slug: str) -> str:
    return slug.replace("_", " ").title()


def _color(slug: str) -> str:
    idx = int(hashlib.md5(slug.encode()).hexdigest(), 16) % len(_CAT_PALETTE)
    return _CAT_PALETTE[idx]


def _category_fields(doc_type: str):
    return [f for f in get_type(doc_type).fields if f.kind == "category"]


def known_categories(session: Session, doc_type: str) -> list[CategoryOption]:
    """Schema seed options ∪ category values already stored for this type, deduped by value."""
    by_value: dict[str, CategoryOption] = {}
    for field in _category_fields(doc_type):
        for opt in field.options or []:
            by_value[opt.value] = opt

    docs = session.exec(
        select(Document).where(Document.doc_type == doc_type, Document.status == "done")
    ).all()
    for d in docs:
        for f in d.fields or []:
            if f.get("kind") != "category":
                continue
            slug = slugify(f.get("value"))
            if slug and slug not in by_value:
                by_value[slug] = CategoryOption(value=slug, label=_label(slug), color=_color(slug))
    return list(by_value.values())


def category_choices(session: Session, doc_type: str) -> dict[str, list[str]]:
    """Per category-field key → list of known category values, to prime the parser prompt."""
    known = [o.value for o in known_categories(session, doc_type)]
    return {f.key: known for f in _category_fields(doc_type)}


def resolve_categories(
    session: Session, doc_type: str, fields: list[ValidatedField], raw_fields: dict
) -> None:
    """Set each category field's value (reuse-or-discover) and attach the full known set as
    options, so the pill + dropdown render. Mutates ``fields`` in place."""
    cat_keys = {f.key for f in _category_fields(doc_type)}
    if not cat_keys:
        return
    registry = known_categories(session, doc_type)
    by_value = {o.value: o for o in registry}

    for vf in fields:
        if vf.kind != "category":
            continue
        raw = raw_fields.get(vf.key) if isinstance(raw_fields.get(vf.key), dict) else {}
        slug = slugify((raw or {}).get("value"))
        if slug and slug not in by_value:
            opt = CategoryOption(value=slug, label=_label(slug), color=_color(slug))
            registry.append(opt)
            by_value[slug] = opt
        vf.value = slug if slug in by_value else ""
        vf.options = list(registry)
        vf.confidence = "high"
