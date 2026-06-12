"""Ollama wrapper — all LLM calls (classify, parse, QA) go through here, never an external API."""

from __future__ import annotations

import json
import re

from ollama import Client

from ..config import settings
from ..schema_def import get_type, doc_types, load_schema

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = Client(host=settings.ollama_host)
    return _client


def _chat_json(prompt: str, system: str, num_predict: int = 256) -> dict:
    resp = client().chat(
        model=settings.ollama_model,
        format="json",
        keep_alive="30m",
        options={"temperature": 0, "num_predict": num_predict},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    content = resp["message"]["content"]
    return json.loads(content)


def warmup() -> None:
    """Load the model into VRAM (keep_alive) so the first real classify/parse isn't cold."""
    client().chat(
        model=settings.ollama_model,
        keep_alive="30m",
        options={"num_predict": 1},
        messages=[{"role": "user", "content": "hi"}],
    )


_HEURISTIC_MIN_SCORE = 2  # need at least this many signal hits to override an 'other' verdict


def _heuristic_type(ocr_text: str) -> str | None:
    """Deterministic fallback: score each type by how many of its schema ``signals`` appear in
    the text (word-boundary, case-insensitive). Returns the best-scoring concrete type if it
    clears ``_HEURISTIC_MIN_SCORE``, else None. ``other`` has no signals so it never wins."""
    text = ocr_text.lower()
    best_type: str | None = None
    best_score = 0
    for name, type_def in load_schema().types.items():
        score = sum(
            1
            for sig in type_def.signals
            if re.search(rf"\b{re.escape(sig.lower())}\b", text)
        )
        if score > best_score:
            best_type, best_score = name, score
    return best_type if best_score >= _HEURISTIC_MIN_SCORE else None


def _type_catalogue() -> str:
    """One line per type — key, label, description and signals — to ground the small model."""
    lines = []
    for name, t in load_schema().types.items():
        signals = f" Signals: {', '.join(t.signals)}." if t.signals else ""
        lines.append(f"- {name} ({t.label}): {t.description}{signals}")
    return "\n".join(lines)


def classify_type(ocr_text: str) -> str:
    types = doc_types()
    system = (
        "You classify administrative documents into ONE type. Reply ONLY with JSON "
        '{"type": "<one of the allowed type keys>"}. A receipt, till slip, cash bill or '
        "point-of-sale slip is an 'invoice'. Choose 'other' ONLY when the document genuinely "
        "matches none of the described types."
    )
    prompt = (
        f"Allowed types:\n{_type_catalogue()}\n\n"
        "Examples:\n"
        'Text: "INDAH GIFT & HOME DECO ... RECEIPT ... TOTAL RM 50.00 ... Change Due RM 34.10" '
        '=> {"type": "invoice"}\n'
        'Text: "SERVICE AGREEMENT ... between Party A and Party B ... hereby agree" '
        '=> {"type": "contract"}\n\n'
        "Pick the single best matching type for this document.\n\n"
        f"Document text:\n{ocr_text[:4000]}"
    )
    try:
        out = _chat_json(prompt, system, num_predict=32)
        t = str(out.get("type", "")).lower().strip()
        llm_type = t if t in types else "other"
    except (json.JSONDecodeError, KeyError):
        llm_type = "other"

    # Guardrail: the small model over-picks 'other'. If keyword signals strongly point to a
    # concrete type, trust them over the LLM's 'other'.
    if llm_type == "other":
        return _heuristic_type(ocr_text) or "other"
    return llm_type


def parse_fields(doc_type: str, ocr_text: str, category_choices: dict | None = None) -> dict:
    """Return raw {"fields": {key: {value, confidence}}}. Re-prompts once on invalid JSON.

    ``category_choices`` maps a category field key to the list of already-known category values;
    the model is told to reuse one before inventing a new one (keeps discovery stable)."""
    type_def = get_type(doc_type)
    category_choices = category_choices or {}
    field_specs = []
    for f in type_def.fields:
        spec = {"key": f.key, "label": f.label, "kind": f.kind}
        if f.hint:
            spec["hint"] = f.hint
        if f.kind == "category":
            spec["known"] = category_choices.get(f.key) or [o.value for o in (f.options or [])]
        field_specs.append(spec)
    keys = [f["key"] for f in field_specs]

    system = (
        "You extract fields from administrative documents. Reply ONLY with strict JSON of the form "
        '{"fields": {"<key>": {"value": "<string>", "confidence": "high|med|low"}}}. '
        "Use the document's own language for values. If a field is absent, omit it. "
        "For a category field (it has a 'known' list), REUSE one of those known categories if it "
        "fits; only if none fit, propose ONE new short category (1-3 words, lowercase). "
        "Set confidence to 'high' when the value is explicit and unambiguous, 'med' when inferred, "
        "'low' when uncertain."
    )
    prompt = (
        f"Document type: {doc_type}.\n"
        f"Extract these fields (keys): {keys}.\n"
        f"Field descriptions: {field_specs}.\n\n"
        f"Document text:\n{ocr_text[:6000]}"
    )

    for _ in range(2):
        try:
            out = _chat_json(prompt, system, num_predict=512)
            fields = _coerce_field_map(out)
            if fields:
                return {"fields": fields}
        except (json.JSONDecodeError, KeyError):
            continue
    return {"fields": {}}


def _coerce_field_map(out: dict) -> dict:
    """Tolerate small-model shape drift: the field map may come wrapped in {"fields": {...}}
    or returned bare ({"date": {...}, "total": {...}}). Returns {} if neither matches."""
    if isinstance(out.get("fields"), dict):
        return out["fields"]
    if isinstance(out, dict) and out and all(isinstance(v, dict) for v in out.values()):
        return out  # bare {key: {value, confidence}} map without the wrapper
    return {}


def summarize_doc(doc_type: str, fields: list[dict], ocr_text: str) -> str:
    """One concise French sentence summarizing the document (TL;DR shown in the viewer)."""
    field_summary = {
        f["key"]: f.get("value")
        for f in fields
        if f.get("kind") == "value" and f.get("value") not in (None, "—", "")
    }
    system = (
        "Tu résumes un document administratif en UNE seule phrase courte et factuelle, en "
        "français. Pas de préambule, pas de liste — juste la phrase. Pour les montants et "
        "dates, recopie EXACTEMENT les valeurs des champs extraits (devise comprise) — "
        "n'utilise pas les montants du texte brut."
    )
    prompt = (
        f"Type: {doc_type}.\n"
        f"Champs extraits: {json.dumps(field_summary, ensure_ascii=False)}\n\n"
        f"Texte:\n{ocr_text[:2000]}"
    )
    try:
        resp = client().chat(
            model=settings.ollama_model,
            keep_alive="30m",
            options={"temperature": 0, "num_predict": 80},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return str(resp["message"]["content"]).strip()
    except Exception:  # noqa: BLE001 — TL;DR is best-effort; never fail the pipeline
        return ""


def answer_question(ocr_text: str, fields: list[dict], question: str) -> dict:
    """Return {"answer": str, "source": str} — source is a verbatim quote from the document."""
    field_summary = {f["key"]: f.get("value") for f in fields if f.get("value") not in (None, "—", "")}
    system = (
        "You answer questions about a single administrative document, using ONLY the provided text "
        "and fields. Reply ONLY with JSON {\"answer\": \"<short answer>\", \"source\": \"<verbatim "
        "snippet copied from the document text that supports the answer>\"}. "
        "If the answer is not in the document, set answer to say so and source to \"\". "
        "Answer in the same language as the question."
    )
    prompt = (
        f"Extracted fields: {json.dumps(field_summary, ensure_ascii=False)}\n\n"
        f"Document text:\n{ocr_text[:6000]}\n\n"
        f"Question: {question}"
    )
    try:
        out = _chat_json(prompt, system, num_predict=384)
        return {"answer": str(out.get("answer", "")), "source": str(out.get("source", ""))}
    except (json.JSONDecodeError, KeyError):
        return {"answer": "We couldn't generate an answer for that.", "source": ""}
