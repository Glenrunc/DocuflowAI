"""Ollama wrapper — all LLM calls (classify, parse, QA) go through here, never an external API."""

from __future__ import annotations

import json
import time

from ollama import Client

from ..config import settings
from ..schema_def import get_type, doc_types

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


def answer_corpus(question: str, corpus: str) -> str:
    """Answer a free-form question over the whole document collection (prose, not JSON)."""
    system = (
        "You answer questions about a COLLECTION of administrative documents, using ONLY the "
        "provided digest (per-document extracted fields and aggregate stats). Be concise and "
        "factual. If the digest doesn't contain the information, say so. Answer in the same "
        "language as the question."
    )
    resp = client().chat(
        model=settings.ollama_model,
        keep_alive="30m",
        options={"temperature": 0, "num_predict": 512},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Document digest:\n{corpus}\n\nQuestion: {question}"},
        ],
    )
    return str(resp["message"]["content"]).strip()


_QA_PERSONA = (
    "Tu es l'assistant de DocuFlow, une application qui extrait et organise des documents "
    "administratifs (factures, contrats, documents médicaux, rapports, pièces d'identité). "
    "Tu réponds aux questions de l'utilisateur sur SA collection de documents en te basant "
    "UNIQUEMENT sur le digest fourni (champs extraits par document + statistiques agrégées). "
    "Si l'information n'y figure pas, dis-le. Réfléchis BRIÈVEMENT, puis réponds de façon "
    "concise et factuelle, dans la langue de la question."
)


THINK_BUDGET_S = 6.0  # how long to let the reasoning model "think out loud" before answering


def stream_corpus(question: str, corpus: str):
    """Stream the global Q&A: yields {'type': 'thinking'|'answer', 'text': <delta>} chunks.

    Phase 1: the reasoning model (qa_model) thinks out loud, streamed live, for up to
    THINK_BUDGET_S seconds. Phase 2: the fast model writes the actual answer — qwen3's
    reasoning is unbounded/verbose, so a hard token cap starved the answer; this time-boxes
    the thinking and guarantees a clean, concise answer."""
    user = {"role": "user", "content": f"Digest des documents:\n{corpus}\n\nQuestion: {question}"}

    t0 = time.monotonic()
    answered = False
    stream = client().chat(
        model=settings.ollama_qa_model,
        think=True,
        stream=True,
        keep_alive="10m",
        options={"temperature": 0, "num_predict": 4096},
        messages=[{"role": "system", "content": _QA_PERSONA}, user],
    )
    for chunk in stream:
        msg = chunk.message
        if msg.thinking:
            yield {"type": "thinking", "text": msg.thinking}
            if time.monotonic() - t0 > THINK_BUDGET_S:
                stream.close()
                break
        if msg.content:
            answered = True
            yield {"type": "answer", "text": msg.content}

    if answered:
        return  # the reasoning model finished thinking and answered within the budget

    # Time-boxed out: produce a clean concise answer with the fast (non-thinking) model.
    for chunk in client().chat(
        model=settings.ollama_model,
        stream=True,
        keep_alive="30m",
        options={"temperature": 0, "num_predict": 512},
        messages=[{"role": "system", "content": _QA_PERSONA}, user],
    ):
        if chunk.message.content:
            yield {"type": "answer", "text": chunk.message.content}


def warmup() -> None:
    """Load the model into VRAM (keep_alive) so the first real classify/parse isn't cold."""
    client().chat(
        model=settings.ollama_model,
        keep_alive="30m",
        options={"num_predict": 1},
        messages=[{"role": "user", "content": "hi"}],
    )


def classify_type(ocr_text: str) -> str:
    types = doc_types()
    system = (
        "You classify administrative documents. Reply ONLY with JSON "
        '{"type": "<one of the allowed types>"}.'
    )
    prompt = (
        f"Allowed types: {types}.\n"
        "Pick the single best matching type for this document. If none fit, use 'other'.\n\n"
        f"Document text:\n{ocr_text[:4000]}"
    )
    try:
        out = _chat_json(prompt, system, num_predict=32)
        t = str(out.get("type", "")).lower().strip()
        return t if t in types else "other"
    except (json.JSONDecodeError, KeyError):
        return "other"


def parse_fields(doc_type: str, ocr_text: str) -> dict:
    """Return raw {"fields": {key: {value, confidence}}}. Re-prompts once on invalid JSON."""
    type_def = get_type(doc_type)
    field_specs = [
        {"key": f.key, "label": f.label, "kind": f.kind}
        for f in type_def.fields
        if f.kind == "value"
    ]
    keys = [f["key"] for f in field_specs]

    system = (
        "You extract fields from administrative documents. Reply ONLY with strict JSON of the form "
        '{"fields": {"<key>": {"value": "<string>", "confidence": "high|med|low"}}}. '
        "Use the document's own language for values. If a field is absent, omit it. "
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
            out = _chat_json(prompt, system, num_predict=384)
            if isinstance(out.get("fields"), dict):
                return out
        except (json.JSONDecodeError, KeyError):
            continue
    return {"fields": {}}


def summarize_doc(doc_type: str, fields: list[dict], ocr_text: str) -> str:
    """One concise French sentence summarizing the document (TL;DR shown in the viewer)."""
    field_summary = {
        f["key"]: f.get("value")
        for f in fields
        if f.get("kind") == "value" and f.get("value") not in (None, "—", "")
    }
    system = (
        "Tu résumes un document administratif en UNE seule phrase courte et factuelle, en "
        "français. Pas de préambule, pas de liste — juste la phrase."
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
