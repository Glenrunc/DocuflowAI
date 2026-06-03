"""Agentic RAG for cross-document Q&A.

ReAct-style loop: the LLM reasons, picks a tool, observes the result, and repeats
until it has enough information to answer. Tools give it targeted access to the
document collection instead of stuffing everything into the context.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter

from sqlmodel import Session, select

from ..config import settings
from ..models import Chunk, Document
from ..schema_def import PLACEHOLDER, doc_types, get_type
from ..summary_calc import parse_money
from .embed import cosine_similarity, embed_query
from .llm import client

logger = logging.getLogger(__name__)

_TOOL_DEFS = [
    {
        "name": "search",
        "description": "Semantic vector search across all documents (natural-language query, NOT a key:value filter). Returns the most relevant text chunks.",
        "params": {"query": "string — a natural-language search query"},
    },
    {
        "name": "filter",
        "description": "List documents matching a type and/or keyword filter.",
        "params": {"type": "string (optional) — document type", "keyword": "string (optional) — text to match in filename or fields"},
    },
    {
        "name": "detail",
        "description": "Get full extracted fields and OCR text of a specific document.",
        "params": {"doc_id": "string — the document ID"},
    },
    {
        "name": "aggregate",
        "description": "Compute sum, average, count, or min/max on a numeric field across documents of a given type.",
        "params": {"type": "string — document type", "field": "string — the EXACT field key (e.g. total, taxes), not a free label", "op": "string — one of: sum, avg, count, min, max"},
    },
    {
        "name": "answer",
        "description": "Provide the final answer to the user. Use this when you have enough information.",
        "params": {"text": "string — the final answer"},
    },
]


def _tool_catalogue() -> str:
    lines = []
    for t in _TOOL_DEFS:
        params = ", ".join(f"{k}: {v}" for k, v in t["params"].items())
        lines.append(f'- {t["name"]}({params}): {t["description"]}')
    return "\n".join(lines)


_SYSTEM = (
    "Tu es l'assistant intelligent de DocuFlow. Tu réponds aux questions sur une collection "
    "de documents administratifs en utilisant les OUTILS disponibles pour chercher et analyser.\n\n"
    "OUTILS DISPONIBLES:\n{tools}\n\n"
    "RÈGLES:\n"
    "1. Réfléchis d'abord à ce dont tu as besoin, puis appelle UN outil.\n"
    "2. Réponds UNIQUEMENT avec du JSON valide: "
    '   {{"thought": "ton raisonnement", "action": "nom_outil", "params": {{...}}}}\n'
    "3. Dès que tu as assez d'info, choisis l'action 'answer' (params vide) — la réponse "
    "finale sera rédigée ensuite, n'écris pas le texte ici.\n"
    "4. Sois concis et factuel. Réponds dans la langue de la question.\n"
    "5. Si tu ne trouves pas l'info, choisis quand même 'answer'.\n"
    "6. Maximum {max_steps} étapes — ne tourne pas en boucle."
)


# Synonyms the model tends to invent → canonical field key.
_FIELD_ALIASES = {
    "amount": "total", "montant": "total", "somme": "total", "prix": "total",
    "price": "total", "spend": "total", "cost": "total", "sum": "total",
}


def _schema_hint() -> str:
    """Per-type field keys so the agent uses real keys (e.g. 'total') instead of guessing."""
    lines = []
    for t in doc_types():
        keys = ", ".join(f.key for f in get_type(t).fields)
        if keys:
            lines.append(f"  {t}: {keys}")
    return "Champs disponibles par type (utilise EXACTEMENT ces clés pour aggregate/detail):\n" + "\n".join(lines)


def _format_doc_summary(doc: Document) -> str:
    fields_str = "; ".join(
        f"{f.get('label', f.get('key'))}={f.get('value', '')}"
        for f in (doc.fields or [])
        if f.get("kind") == "value" and f.get("value") not in (None, "", PLACEHOLDER)
    )
    return f"[{doc.id[:8]}] {doc.filename} ({doc.doc_type}) — {fields_str or '(no fields)'}"


# ── Tool implementations ──────────────────────────────────────────────

def _tool_search(session: Session, params: dict) -> str:
    query = params.get("query", "")
    if not query:
        return "Error: query is required."

    query_vec = embed_query(query)
    chunks = session.exec(select(Chunk)).all()
    if not chunks:
        return "No documents have been embedded yet."

    scored = []
    for c in chunks:
        if not c.embedding:
            continue
        score = cosine_similarity(query_vec, c.embedding)
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: settings.agent_top_k]

    if not top:
        return "No relevant chunks found."

    results = []
    for score, chunk in top:
        doc = session.get(Document, chunk.doc_id)
        fname = doc.filename if doc else "?"
        dtype = doc.doc_type if doc else "?"
        results.append(
            f"[score={score:.2f}] {fname} ({dtype}, page {chunk.page}):\n{chunk.content[:400]}"
        )
    return "\n---\n".join(results)


def _tool_filter(session: Session, params: dict) -> str:
    doc_type = params.get("type")
    keyword = (params.get("keyword") or "").strip().lower()

    stmt = select(Document).where(Document.status == "done")
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    docs = session.exec(stmt.order_by(Document.created_at)).all()

    if keyword:
        filtered = []
        for d in docs:
            searchable = d.filename.lower() + " " + json.dumps(d.fields or [], ensure_ascii=False).lower()
            if keyword in searchable:
                filtered.append(d)
        docs = filtered

    if not docs:
        return "No documents match this filter."

    lines = [_format_doc_summary(d) for d in docs[:20]]
    total = len(docs)
    header = f"{total} document(s) found"
    if total > 20:
        header += f" (showing first 20)"
    return f"{header}:\n" + "\n".join(lines)


def _tool_detail(session: Session, params: dict) -> str:
    doc_id = params.get("doc_id", "")
    if len(doc_id) == 8:
        docs = session.exec(select(Document).where(Document.status == "done")).all()
        match = [d for d in docs if d.id.startswith(doc_id)]
        if len(match) == 1:
            doc_id = match[0].id

    doc = session.get(Document, doc_id)
    if doc is None:
        return f"Document '{doc_id}' not found."

    fields_str = "\n".join(
        f"  {f.get('label', f.get('key'))}: {f.get('value', '')}"
        for f in (doc.fields or [])
    )
    ocr_preview = (doc.ocr_text or "")[:2000]
    return (
        f"Filename: {doc.filename}\n"
        f"Type: {doc.doc_type}\n"
        f"Fields:\n{fields_str}\n\n"
        f"OCR text (first 2000 chars):\n{ocr_preview}"
    )


def _tool_aggregate(session: Session, params: dict) -> str:
    doc_type = params.get("type")
    field_key = params.get("field")
    op = params.get("op", "sum")
    if not doc_type or not field_key:
        return "Error: 'type' and 'field' are required."

    docs = session.exec(
        select(Document).where(Document.doc_type == doc_type, Document.status == "done")
    ).all()
    if not docs:
        return f"No '{doc_type}' documents found."

    target = _FIELD_ALIASES.get(field_key.strip().lower(), field_key.strip().lower())
    values: list[float] = []
    for d in docs:
        for f in (d.fields or []):
            # the model may pass the field key ('total'), its label ('Total'), or a synonym
            if target in (str(f.get("key", "")).lower(), str(f.get("label", "")).lower()):
                v = parse_money(f.get("value", ""))
                if v is not None:
                    values.append(v)

    if not values:
        return f"No numeric values found for field '{field_key}' in '{doc_type}' documents."

    if op == "sum":
        result = sum(values)
    elif op == "avg":
        result = sum(values) / len(values)
    elif op == "count":
        result = len(values)
    elif op == "min":
        result = min(values)
    elif op == "max":
        result = max(values)
    else:
        return f"Unknown operation '{op}'. Use: sum, avg, count, min, max."

    return f"{op}({field_key}) for {len(docs)} {doc_type} docs ({len(values)} valid values) = {result:.2f}"


_TOOLS = {
    "search": _tool_search,
    "filter": _tool_filter,
    "detail": _tool_detail,
    "aggregate": _tool_aggregate,
}


# ── Agent loop ─────────────────────────────────────────────────────────

def _parse_action(text: str) -> dict | None:
    """Extract JSON action from model output, tolerating markdown fences."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    elif text.startswith("{"):
        pass
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


_ANSWER_PROMPT = (
    "Tu as assez d'information. Rédige MAINTENANT la réponse finale pour l'utilisateur, "
    "en te basant sur les observations ci-dessus. Concise, factuelle, dans la langue de la "
    "question. Ne renvoie PAS de JSON, juste la réponse."
)


def _stream_answer(messages: list[dict]):
    """One final, streamed generation on the fast model — gives an immediate response feel."""
    msgs = messages + [{"role": "user", "content": _ANSWER_PROMPT}]
    for chunk in client().chat(
        model=settings.ollama_model,
        stream=True,
        keep_alive="30m",
        options={"temperature": 0, "num_predict": 512},
        messages=msgs,
    ):
        content = chunk["message"]["content"]
        if content:
            yield {"type": "answer", "text": content}


def run_agent(session: Session, question: str):
    """Generator that yields streaming events as the agent reasons and acts.

    Yields dicts: {'type': 'thinking'|'tool'|'answer', 'text': str}
    """
    system = _SYSTEM.format(tools=_tool_catalogue(), max_steps=settings.agent_max_steps)

    collection_stats = _build_stats(session)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Contexte de la collection:\n{collection_stats}\n\n"
            f"{_schema_hint()}\n\n"
            f"Question de l'utilisateur: {question}"
        )},
    ]

    for step in range(settings.agent_max_steps):
        try:
            resp = client().chat(
                model=settings.ollama_model,
                format="json",
                keep_alive="30m",
                options={"temperature": 0, "num_predict": 192},
                messages=messages,
            )
            raw = resp["message"]["content"]
        except Exception:
            logger.exception("agent LLM call failed at step %d", step)
            yield {"type": "answer", "text": "Une erreur est survenue pendant la recherche."}
            return

        action = _parse_action(raw)
        if action is None:
            yield {"type": "answer", "text": raw}
            return

        thought = action.get("thought", "")
        action_name = action.get("action", "")
        params = action.get("params", {})

        if thought:
            yield {"type": "thinking", "text": thought}

        if action_name == "answer":
            yield from _stream_answer(messages)
            return

        tool_fn = _TOOLS.get(action_name)
        if tool_fn is None:
            observation = f"Unknown tool '{action_name}'. Available: {list(_TOOLS.keys())} and 'answer'."
        else:
            yield {"type": "tool", "text": f"🔧 {action_name}({json.dumps(params, ensure_ascii=False)})"}
            try:
                observation = tool_fn(session, params)
            except Exception as e:
                logger.exception("tool %s failed", action_name)
                observation = f"Tool error: {e}"

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation:\n{observation}"})

    yield from _stream_answer(messages)  # step budget exhausted — answer from what we have


def _build_stats(session: Session) -> str:
    """Compact collection overview so the agent knows what's available before searching."""
    docs = session.exec(select(Document).where(Document.status == "done")).all()
    if not docs:
        return "Collection vide — aucun document traité."
    type_counts = Counter(d.doc_type for d in docs if d.doc_type)
    total = len(docs)
    types_str = ", ".join(f"{t}: {n}" for t, n in type_counts.most_common())
    return f"{total} documents traités. Types: {types_str}."


def stream_agent(session: Session, question: str):
    """Wrap run_agent for the NDJSON streaming route."""
    for event in run_agent(session, question):
        yield event
