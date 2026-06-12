"""Agentic RAG for cross-document Q&A.

Clean ReAct loop: the model reasons, picks a tool, observes the result,
and repeats until it has enough information to answer. No hardcoded routing,
no LLM reranking — the model decides autonomously.
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
from .embed import embed_query, hybrid_search, search_bm25, search_vectors
from .llm import client

logger = logging.getLogger(__name__)


# ── Tool catalogue (shown to the model in the prompt) ────────────────

_TOOL_DEFS = [
    {
        "name": "search",
        "params": "query: string",
        "description": (
            "Recherche hybride (sémantique + mots-clés) dans tous les documents. "
            "Utilise des mots-clés en français."
        ),
    },
    {
        "name": "filter",
        "params": "type?: string (invoice|quote|contract|medical|report|id), keyword?: string",
        "description": "Liste les documents par type et/ou mot-clé. Utile pour compter ou lister.",
    },
    {
        "name": "detail",
        "params": "doc_id: string",
        "description": (
            "Récupère le texte OCR complet et les champs d'un document. "
            "Indispensable pour lire le contenu détaillé (cahier des charges, clauses, descriptions). "
            "Utilise l'ID court [xxxxxxxx] retourné par search/filter."
        ),
    },
    {
        "name": "aggregate",
        "params": "type?: string, field: string, op: sum|avg|count|min|max",
        "description": "Calcule un agrégat sur un champ numérique (total, value, etc.).",
    },
    {
        "name": "answer",
        "params": "text: string",
        "description": "Donne la réponse finale quand tu as assez d'information.",
    },
]


def _tool_catalogue() -> str:
    return "\n".join(
        f'- {t["name"]}({t["params"]}): {t["description"]}'
        for t in _TOOL_DEFS
    )


# ── System prompt ─────────────────────────────────────────────────────

_SYSTEM = (
    "Tu es l'assistant intelligent de DocuFlow, une application de gestion documentaire. "
    "Tu réponds aux questions sur une collection de documents administratifs (factures, devis, "
    "contrats, documents médicaux, rapports, pièces d'identité).\n\n"
    "OUTILS DISPONIBLES:\n{tools}\n\n"
    "FONCTIONNEMENT:\n"
    "1. Réfléchis à ce dont tu as besoin (thought), puis appelle UN outil (action).\n"
    '2. Réponds UNIQUEMENT en JSON: {{"thought": "...", "action": "nom", "params": {{...}}}}\n'
    "3. Quand tu as assez d'info, utilise 'answer'.\n\n"
    "CONSEILS:\n"
    "- Pour le contenu détaillé d'un document (cahier des charges, clauses, descriptions), "
    "utilise 'detail' avec son ID.\n"
    "- Pour trouver un document lié (ex: facture associée à un devis), cherche par montant, "
    "client ou référence.\n"
    "- Si une recherche ne donne rien, reformule avec d'autres mots-clés.\n"
    "- Utilise des mots-clés en FRANÇAIS pour 'search'.\n"
    "- Réponds TOUJOURS en français, de façon concise et factuelle.\n"
    "- IMPORTANT: dans ta réponse finale ('answer'), cite les données concrètes trouvées "
    "(montants, dates, noms, numéros). Ne dis pas juste 'l'information est disponible'.\n"
    "- Maximum {max_steps} étapes.\n"
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


# ── Tool implementations ─────────────────────────────────────────────

def _format_doc_summary(doc: Document) -> str:
    fields_str = "; ".join(
        f"{f.get('label', f.get('key'))}={f.get('value', '')}"
        for f in (doc.fields or [])
        if f.get("kind") == "value" and f.get("value") not in (None, "", PLACEHOLDER)
    )
    return f"[{doc.id[:8]}] {doc.filename} ({doc.doc_type}) — {fields_str or '(no fields)'}"


def _tool_search(session: Session, params: dict) -> str:
    query = params.get("query", "")
    if not query:
        return "Erreur: query est requis."

    try:
        query_vec = embed_query(query)
    except Exception:
        logger.exception("embed_query failed")
        results = search_bm25(session, query, settings.agent_top_k)
        if not results:
            return "Aucun résultat trouvé."
        return _format_search_results(session, results)

    results = hybrid_search(session, query, query_vec, top_k=settings.agent_top_k)

    if not results:
        results = search_vectors(session, query_vec, settings.agent_top_k)

    if not results:
        return "Aucun résultat trouvé."

    return _format_search_results(session, results)


def _format_search_results(session: Session, results: list[dict]) -> str:
    formatted = []
    seen_docs: set[str] = set()
    unique_doc_ids = {r["doc_id"] for r in results}
    extended = len(unique_doc_ids) <= 3
    content_limit = 1500 if extended else 500

    for r in results:
        doc = session.get(Document, r["doc_id"])
        fname = doc.filename if doc else "?"
        dtype = doc.doc_type if doc else "?"
        score_key = "rrf_score" if "rrf_score" in r else "score"
        score = r.get(score_key, 0)

        fields_str = ""
        ocr_extra = ""
        if doc and r["doc_id"] not in seen_docs:
            seen_docs.add(r["doc_id"])
            if doc.fields:
                fields_str = "\n  Champs: " + "; ".join(
                    f"{f.get('label', f.get('key'))}={f.get('value', '')}"
                    for f in doc.fields
                    if f.get("kind") == "value" and f.get("value") not in (None, "", PLACEHOLDER)
                )
            if doc.summary:
                fields_str += f"\n  Résumé: {doc.summary}"
            if extended and doc.ocr_text:
                ocr_extra = f"\n  Texte OCR complet:\n{doc.ocr_text[:3000]}"

        formatted.append(
            f"{fname} ({dtype}, p.{r['page']}, score={score:.3f})"
            f"{fields_str}\n"
            f"  Extrait: {r['content'][:content_limit]}"
            f"{ocr_extra}"
        )
    return "\n---\n".join(formatted)


def _tool_filter(session: Session, params: dict) -> str:
    doc_type = params.get("type")
    keyword = (params.get("keyword") or "").strip().lower()

    stmt = select(Document).where(Document.status == "done")
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    docs = session.exec(stmt.order_by(Document.created_at)).all()

    if keyword:
        # Extract numbers from keyword for flexible numeric matching
        kw_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", keyword))

        def _matches(d: Document) -> bool:
            searchable = d.filename.lower() + " " + json.dumps(d.fields or [], ensure_ascii=False).lower()
            if keyword in searchable:
                return True
            # Fuzzy number matching: "280 euros" matches "280,00 €"
            if kw_numbers:
                doc_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", searchable))
                for kn in kw_numbers:
                    base = kn.replace(",", ".").rstrip("0").rstrip(".")
                    for dn in doc_numbers:
                        dn_base = dn.replace(",", ".").rstrip("0").rstrip(".")
                        if base == dn_base:
                            return True
            return False

        docs = [d for d in docs if _matches(d)]

    if not docs:
        return "Aucun document ne correspond à ce filtre."

    lines = [_format_doc_summary(d) for d in docs[:20]]
    total = len(docs)
    header = f"{total} document(s) trouvé(s)"
    if total > 20:
        header += " (20 premiers affichés)"
    return f"{header}:\n" + "\n".join(lines)


def _tool_detail(session: Session, params: dict) -> str:
    doc_id = params.get("doc_id", "").strip().strip("[]")
    if not doc_id:
        return "Erreur: 'doc_id' est requis."
    docs = session.exec(select(Document).where(Document.status == "done")).all()

    doc = None
    if len(doc_id) <= 8:
        match = [d for d in docs if d.id.startswith(doc_id)]
        if len(match) == 1:
            doc = match[0]
        elif len(match) > 1:
            return f"Plusieurs documents pour '{doc_id}': " + ", ".join(
                f"[{d.id[:8]}] {d.filename}" for d in match[:5]
            )

    if doc is None:
        exact = [d for d in docs if d.filename == doc_id]
        if len(exact) == 1:
            doc = exact[0]
        elif not exact:
            partial = [
                d for d in docs
                if doc_id.lower() in d.filename.lower() or d.filename.lower() in doc_id.lower()
            ]
            if len(partial) == 1:
                doc = partial[0]
            elif len(partial) > 1:
                return f"Plusieurs documents pour '{doc_id}': " + ", ".join(
                    f"[{d.id[:8]}] {d.filename}" for d in partial[:5]
                )

    if doc is None:
        doc = session.get(Document, doc_id)

    if doc is None:
        return f"Document '{doc_id}' introuvable."

    fields_str = "\n".join(
        f"  {f.get('label', f.get('key'))}: {f.get('value', '')} (confiance: {f.get('confidence', '?')})"
        for f in (doc.fields or [])
    )
    ocr_preview = (doc.ocr_text or "")[:5000]
    return (
        f"Fichier: {doc.filename}\n"
        f"Type: {doc.doc_type}\n"
        f"Pages: {doc.page_count}\n"
        f"Résumé: {doc.summary or '(aucun)'}\n"
        f"Champs extraits:\n{fields_str}\n\n"
        f"Texte OCR:\n{ocr_preview}"
    )


def _tool_aggregate(session: Session, params: dict) -> str:
    doc_type = params.get("type")
    field_key = params.get("field")
    op = params.get("op", "sum")
    if not field_key:
        return "Erreur: 'field' est requis."

    if doc_type:
        docs = session.exec(
            select(Document).where(Document.doc_type == doc_type, Document.status == "done")
        ).all()
        if not docs:
            docs = session.exec(
                select(Document).where(Document.status == "done")
            ).all()
    else:
        docs = session.exec(
            select(Document).where(Document.status == "done")
        ).all()

    if not docs:
        return "Aucun document traité trouvé."

<<<<<<< HEAD
    target = _FIELD_ALIASES.get(field_key.strip().lower(), field_key.strip().lower())
    values: list[float] = []
    for d in docs:
        for f in (d.fields or []):
            # the model may pass the field key ('total'), its label ('Total'), or a synonym
            if target in (str(f.get("key", "")).lower(), str(f.get("label", "")).lower()):
=======
    seen_filenames: set[str] = set()
    unique_docs: list[Document] = []
    for d in docs:
        if d.filename not in seen_filenames:
            seen_filenames.add(d.filename)
            unique_docs.append(d)
    docs = unique_docs

    field_aliases = [field_key, "total", "montant", "amount", "value", "total_ttc", "total_ht"]
    resolved_key = field_key
    for d in docs:
        for f in (d.fields or []):
            fkey = f.get("key", "")
            if fkey in field_aliases:
                resolved_key = fkey
                break
        if resolved_key != field_key:
            break

    values: list[float] = []
    doc_details: list[str] = []
    for d in docs:
        for f in (d.fields or []):
            if f.get("key", "") == resolved_key:
>>>>>>> origin/Agentic-RAG
                v = parse_money(f.get("value", ""))
                if v is not None:
                    values.append(v)
                    doc_details.append(f"  - [{d.id[:8]}] {d.filename}: {f.get('value', '')}")

    if not values:
        return f"Aucune valeur numérique trouvée pour '{field_key}'."

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
        return f"Opération inconnue '{op}'."

    _TYPE_LABELS = {
        "invoice": "factures", "quote": "devis", "contract": "contrats",
        "medical": "docs médicaux", "report": "rapports", "id": "pièces d'identité",
    }
    _OP_LABELS = {"sum": "Somme", "avg": "Moyenne", "count": "Nombre", "min": "Minimum", "max": "Maximum"}
    type_label = _TYPE_LABELS.get(doc_type or "", doc_type or "tous types")
    op_label = _OP_LABELS.get(op, op)

    detail_str = "\n".join(doc_details[:10])
    output = (
        f"{op_label} de '{resolved_key}' sur {len(docs)} {type_label} "
        f"({len(values)} valeurs) = {result:,.2f}€\n"
        f"Détail:\n{detail_str}"
    )

    # For min/max, highlight which document holds the extreme value
    if op in ("min", "max") and doc_details:
        idx = values.index(result)
        output += f"\n→ Le document correspondant: {doc_details[idx].strip()}"

    return output


_TOOL_DISPATCH = {
    "search": _tool_search,
    "filter": _tool_filter,
    "detail": _tool_detail,
    "aggregate": _tool_aggregate,
}


# ── Collection stats ─────────────────────────────────────────────────

def _build_stats(session: Session) -> str:
    docs = session.exec(select(Document).where(Document.status == "done")).all()
    if not docs:
        return "Collection vide — aucun document traité."

    type_counts = Counter(d.doc_type for d in docs if d.doc_type)
    total = len(docs)
    types_str = ", ".join(f"{t}: {n}" for t, n in type_counts.most_common())

    samples: dict[str, list[str]] = {}
    for d in docs:
        t = d.doc_type or "other"
        if t not in samples:
            samples[t] = []
        if len(samples[t]) < 3:
            samples[t].append(d.filename)

    samples_str = "\n".join(
        f"  {t}: {', '.join(names)}" for t, names in samples.items()
    )

    chunk_count = session.exec(select(Chunk)).first()
    embed_status = "Embeddings disponibles" if chunk_count else "Pas d'embeddings"

    return (
        f"{total} documents traités. Types: {types_str}.\n"
        f"{embed_status}.\n"
        f"Exemples:\n{samples_str}"
    )


# ── JSON parsing ─────────────────────────────────────────────────────

def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _parse_action(text: str) -> dict | None:
    text = _strip_think_tags(text)
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    elif not text.startswith("{"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
        return None


<<<<<<< HEAD
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
=======
# ── Answer refinement ────────────────────────────────────────────────

_VAGUE_PATTERNS = re.compile(
    r"(sera\b|va être|est disponible|est mentionné|peut être trouvé|"
    r"je peux (?:vous |te )?(?:dire|donner|fournir)|réponse finale|"
    r"maintenant.*(?:donner|répondre)|les informations\b|"
    r"en raison des limitations)",
    re.IGNORECASE,
)


def _refine_answer(question: str, raw_answer: str, messages: list[dict]) -> str:
    """If the agent's answer is vague/meta, synthesize a better one from observations."""
    if not _VAGUE_PATTERNS.search(raw_answer):
        return raw_answer

    observations = []
    for m in messages:
        if m["role"] == "user" and isinstance(m["content"], str) and m["content"].startswith("Observation:"):
            observations.append(m["content"][len("Observation:\n"):])

    if not observations:
        return raw_answer

    context = "\n---\n".join(observations[-3:])
    try:
        resp = client().chat(
            model=settings.ollama_model,
            keep_alive="30m",
            options={"temperature": 0, "num_predict": 512},
            messages=[
                {"role": "system", "content": (
                    "Tu réponds de façon concise et factuelle en français. "
                    "Cite les données concrètes (montants, dates, noms, descriptions)."
                )},
                {"role": "user", "content": (
                    f"Données collectées:\n{context}\n\nQuestion: {question}"
                )},
            ],
        )
        refined = resp["message"]["content"].strip()
        if refined and len(refined) > 20:
            return refined
    except Exception:
        logger.debug("Answer refinement failed, using original")

    return raw_answer


# ── Agent loop ───────────────────────────────────────────────────────

def run_agent(session: Session, question: str, history: list[tuple[str, str]] | None = None):
    """Generator yielding streaming events as the agent reasons and acts.
>>>>>>> origin/Agentic-RAG

    Yields dicts: {'type': 'thinking'|'tool'|'answer', 'text': str}
    """
    system = _SYSTEM.format(tools=_tool_catalogue(), max_steps=settings.agent_max_steps)
    stats = _build_stats(session)

    messages: list[dict] = [
        {"role": "system", "content": system},
<<<<<<< HEAD
        {"role": "user", "content": (
            f"Contexte de la collection:\n{collection_stats}\n\n"
            f"{_schema_hint()}\n\n"
            f"Question de l'utilisateur: {question}"
        )},
=======
>>>>>>> origin/Agentic-RAG
    ]

    if history:
        for prev_q, prev_a in history:
            messages.append({"role": "user", "content": f"Question: {prev_q}"})
            messages.append({"role": "assistant", "content": json.dumps(
                {"thought": "", "action": "answer", "params": {"text": prev_a}},
                ensure_ascii=False,
            )})

    messages.append({"role": "user", "content": (
        f"Contexte de la collection:\n{stats}\n\nQuestion: {question}"
    )})

    prev_actions: list[str] = []

    for step in range(settings.agent_max_steps):
        try:
            resp = client().chat(
                model=settings.ollama_model,
                format="json",
                keep_alive="30m",
<<<<<<< HEAD
                options={"temperature": 0, "num_predict": 192},
=======
                options={"temperature": 0, "num_predict": 1024},
>>>>>>> origin/Agentic-RAG
                messages=messages,
            )
            raw = resp["message"]["content"]
        except Exception:
            logger.exception("agent LLM call failed at step %d", step)
            yield {"type": "answer", "text": "Une erreur est survenue pendant la recherche."}
            return

        action = _parse_action(raw)
        if action is None:
<<<<<<< HEAD
            yield {"type": "answer", "text": raw}
=======
            clean = _strip_think_tags(raw)
            yield {"type": "answer", "text": clean or "Je n'ai pas pu traiter la demande."}
>>>>>>> origin/Agentic-RAG
            return

        thought = action.get("thought", "")
        action_name = action.get("action", "")
        params = action.get("params", {})

        # Loop detection — nudge the model to try a different approach
        action_sig = f"{action_name}:{json.dumps(params, sort_keys=True)}"
        prev_actions.append(action_sig)
        if prev_actions.count(action_sig) >= 2:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": (
                f"STOP — tu répètes la même action. Rappel: {question}\n"
                "Essaie une approche DIFFÉRENTE: cherche par montant, utilise 'search' "
                "au lieu de 'filter', ou utilise 'answer' si tu as déjà assez d'info."
            )})
            continue  # give the model one more chance with the nudge

        if thought:
            yield {"type": "thinking", "text": thought}

        if action_name == "answer":
<<<<<<< HEAD
            yield from _stream_answer(messages)
=======
            answer_text = params.get("text") or thought or raw
            refined = _refine_answer(question, answer_text, messages)
            yield {"type": "answer", "text": refined}
>>>>>>> origin/Agentic-RAG
            return

        tool_fn = _TOOL_DISPATCH.get(action_name)
        if tool_fn is None:
            observation = f"Outil inconnu '{action_name}'. Disponibles: {list(_TOOL_DISPATCH.keys())} et 'answer'."
        else:
            yield {"type": "tool", "text": f"🔧 {action_name}({json.dumps(params, ensure_ascii=False)})"}
            try:
                observation = tool_fn(session, params)
            except Exception as e:
                logger.exception("tool %s failed", action_name)
                observation = f"Erreur: {e}"

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Observation:\n{observation}"})

<<<<<<< HEAD
    yield from _stream_answer(messages)  # step budget exhausted — answer from what we have
=======
    # Max steps reached — force a final answer
    messages.append({"role": "user", "content": (
        f"Limite d'étapes atteinte. Rappel de la question: {question}\n"
        "Formule ta réponse finale avec les informations collectées "
        "via l'outil 'answer' avec le champ 'text'."
    )})
    try:
        fallback = client().chat(
            model=settings.ollama_qa_model,
            format="json",
            keep_alive="30m",
            options={"temperature": 0, "num_predict": 512},
            messages=messages,
        )
        fb_action = _parse_action(fallback["message"]["content"])
        if fb_action:
            fb_text = fb_action.get("params", {}).get("text") or fb_action.get("thought", "")
            if fb_text:
                yield {"type": "answer", "text": fb_text}
                return
    except Exception:
        pass
    yield {"type": "answer", "text": "J'ai atteint la limite d'étapes sans pouvoir conclure."}
>>>>>>> origin/Agentic-RAG


def stream_agent(session: Session, question: str, history: list[tuple[str, str]] | None = None):
    """Wrap run_agent for the NDJSON streaming route."""
    for event in run_agent(session, question, history=history):
        yield event
