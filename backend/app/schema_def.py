"""Single source of truth for document field schemas.

Loads ``shared/schemas.json`` (shared verbatim with the frontend) and exposes typed
access plus validation of raw LLM parsing output against the detected type's schema.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from .config import settings

Confidence = Literal["high", "med", "low"]
FieldKind = Literal["value", "category"]

PLACEHOLDER = "—"


class CategoryOption(BaseModel):
    value: str
    label: str
    color: str


class FieldDef(BaseModel):
    key: str
    label: str
    icon: str
    kind: FieldKind
    options: list[CategoryOption] | None = None


class PillColors(BaseModel):
    bg: str
    fg: str


class TypeDef(BaseModel):
    label: str
    icon: str
    pill: PillColors
    donut: str
    identifying: list[str]
    dynamic: bool
    fields: list[FieldDef]


class SchemaDoc(BaseModel):
    version: int
    groupOrder: list[str]
    types: dict[str, TypeDef]
    confidenceLevels: list[Confidence]
    bboxPalette: list[str]


@lru_cache(maxsize=1)
def load_schema() -> SchemaDoc:
    raw = json.loads(settings.shared_schema_path.read_text(encoding="utf-8"))
    return SchemaDoc.model_validate(raw)


def doc_types() -> list[str]:
    return load_schema().groupOrder


def get_type(doc_type: str) -> TypeDef:
    schema = load_schema()
    if doc_type not in schema.types:
        raise KeyError(f"unknown document type: {doc_type}")
    return schema.types[doc_type]


class ValidatedField(BaseModel):
    key: str
    label: str
    icon: str
    kind: FieldKind
    value: str
    confidence: Confidence
    options: list[CategoryOption] | None = None


def _coerce_confidence(raw: object) -> Confidence:
    if isinstance(raw, str) and raw.lower() in ("high", "med", "low"):
        return raw.lower()  # type: ignore[return-value]
    return "low"


def validate_fields(doc_type: str, raw_fields: dict) -> list[ValidatedField]:
    """Validate raw LLM output against the schema of ``doc_type``.

    Missing or malformed value fields fall back to ``—`` / ``low``. Category fields
    only accept values present in the schema options; anything else is left blank
    (Uncategorized). For dynamic types (``other``) the LLM-provided key/value pairs are
    accepted as generic rows.
    """
    type_def = get_type(doc_type)
    out: list[ValidatedField] = []

    if type_def.dynamic:
        for key, payload in (raw_fields or {}).items():
            payload = payload if isinstance(payload, dict) else {}
            value = payload.get("value")
            out.append(
                ValidatedField(
                    key=str(key),
                    label=str(key).replace("_", " ").title(),
                    icon="📄",
                    kind="value",
                    value=str(value) if value not in (None, "") else PLACEHOLDER,
                    confidence=_coerce_confidence(payload.get("confidence")),
                )
            )
        return out

    for field in type_def.fields:
        payload = (raw_fields or {}).get(field.key)
        payload = payload if isinstance(payload, dict) else {}

        if field.kind == "category":
            raw_value = payload.get("value")
            allowed = {o.value for o in (field.options or [])}
            value = raw_value if raw_value in allowed else ""
            out.append(
                ValidatedField(
                    key=field.key,
                    label=field.label,
                    icon=field.icon,
                    kind="category",
                    value=value,
                    confidence="high",
                    options=field.options,
                )
            )
            continue

        raw_value = payload.get("value")
        has_value = raw_value not in (None, "", PLACEHOLDER)
        out.append(
            ValidatedField(
                key=field.key,
                label=field.label,
                icon=field.icon,
                kind="value",
                value=str(raw_value) if has_value else PLACEHOLDER,
                confidence=_coerce_confidence(payload.get("confidence")) if has_value else "low",
            )
        )

    return out
