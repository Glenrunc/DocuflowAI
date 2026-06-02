"""Session summary aggregation for the Summary tab (§10). Pure functions over Document rows."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime

from .models import Document
from .schema_def import PLACEHOLDER, get_type

_CONF_SCORE = {"high": 1.0, "med": 0.66, "low": 0.33}


def _value(fields: list[dict], key: str) -> str:
    for f in fields:
        if f.get("key") == key:
            return (f.get("value") or "").strip()
    return ""


def parse_money(s: str) -> float | None:
    m = re.search(r"-?\d[\d\s .,]*", s or "")
    if not m:
        return None
    raw = m.group(0).replace(" ", "").replace(" ", "")  # drop thousands spaces (incl. NBSP)
    has_dot, has_comma = "." in raw, "," in raw
    if has_dot and has_comma:
        # the rightmost of the two is the decimal separator
        dec = "." if raw.rfind(".") > raw.rfind(",") else ","
        thou = "," if dec == "." else "."
        raw = raw.replace(thou, "").replace(dec, ".")
    elif has_comma:
        raw = raw.replace(",", ".")  # FR/EU decimal comma
    try:
        return float(raw)
    except ValueError:
        return None


_FR_MONTHS = {
    "janv": 1, "févr": 2, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "août": 8, "aout": 8, "sept": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12,
}


def parse_date(s: str) -> date | None:
    """Parse FR/ISO dates: '30/06/2026', '2026-11-30', '30 nov. 2026', '1er juin 2026'."""
    s = (s or "").strip().lower()
    if not s:
        return None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)  # ISO
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)  # dd/mm/yyyy
    if m:
        d, mo, y = (int(g) for g in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})(?:er)?\s+([a-zàâäéèêëîïôöùûüç]+)\.?\s+(\d{4})", s)  # 1er juin 2026
    if m:
        d, mon, y = m.group(1), m.group(2), m.group(3)
        for pre, num in _FR_MONTHS.items():
            if mon.startswith(pre):
                try:
                    return date(int(y), num, int(d))
                except ValueError:
                    return None
    return None


# (type, field key) pairs that represent a deadline/expiry on a document.
_EXPIRY_FIELDS = {"contract": "endDate", "id": "expiryDate"}


def doc_expiry(doc: Document) -> date | None:
    key = _EXPIRY_FIELDS.get(doc.doc_type or "")
    if not key:
        return None
    return parse_date(_value(doc.fields or [], key))


def expires_in_days(doc: Document, today: date | None = None) -> int | None:
    d = doc_expiry(doc)
    if d is None:
        return None
    return (d - (today or date.today())).days


def deadlines(docs: list[Document], today: date | None = None) -> list[dict]:
    """Upcoming/expired deadlines across the collection, soonest first."""
    today = today or date.today()
    out = []
    for doc in docs:
        if doc.status != "done":
            continue
        d = doc_expiry(doc)
        if d is None:
            continue
        days = (d - today).days
        status = "expired" if days < 0 else "soon" if days <= 30 else "ok"
        out.append(
            {
                "id": doc.id,
                "filename": doc.filename,
                "type": doc.doc_type,
                "label": "Fin de contrat" if doc.doc_type == "contract" else "Expiration",
                "date": d.isoformat(),
                "daysLeft": days,
                "status": status,
            }
        )
    out.sort(key=lambda x: x["daysLeft"])
    return out


def conf_avg_label(fields: list[dict]) -> str:
    scores = [_CONF_SCORE.get(f.get("confidence", ""), 0.33) for f in fields if f.get("kind") == "value"]
    if not scores:
        return "—"
    avg = sum(scores) / len(scores)
    return "High" if avg >= 0.8 else "Review" if avg >= 0.5 else "Low"


def key_field(doc: Document) -> tuple[str, str]:
    """Return (label, value) of the document's first identifying/value field."""
    if not doc.doc_type:
        return ("", "")
    type_def = get_type(doc.doc_type)
    keys = type_def.identifying or [f.key for f in type_def.fields if f.kind == "value"]
    for k in keys:
        v = _value(doc.fields or [], k)
        if v and v != "—":
            label = next((f.label for f in type_def.fields if f.key == k), k)
            return (label, v)
    return ("", "")


def _date_range(docs: list[Document]) -> dict:
    dates = [d.created_at for d in docs if d.created_at]
    if not dates:
        return {"label": "—", "weeks": 0}
    lo, hi = min(dates), max(dates)
    weeks = max(1, math.ceil((hi - lo).days / 7)) if hi > lo else 1
    fmt = lambda dt: dt.strftime("%b %-d") if hasattr(dt, "strftime") else str(dt)
    label = fmt(lo) if lo == hi else f"{fmt(lo)} – {fmt(hi)}"
    return {"label": label, "weeks": weeks}


def _subsection(doc_type: str, docs: list[Document]) -> dict:
    fields = [d.fields or [] for d in docs]
    if doc_type == "invoice":
        totals = [parse_money(_value(f, "total")) for f in fields]
        total_spend = sum(t for t in totals if t is not None)
        merchants = Counter(_value(f, "merchant") for f in fields if _value(f, "merchant"))
        top = merchants.most_common(1)
        cats = Counter(_value(f, "category") for f in fields if _value(f, "category"))
        cat_total = sum(cats.values()) or 1
        breakdown = {c: round(n * 100 / cat_total) for c, n in cats.items()}
        return {
            "totalSpend": round(total_spend, 2),
            "topMerchant": top[0][0] if top else None,
            "topMerchantCount": top[0][1] if top else 0,
            "categoryBreakdown": breakdown,
        }
    if doc_type == "contract":
        values = [parse_money(_value(f, "value")) for f in fields]
        nums = [v for v in values if v is not None]
        now = datetime.now()
        expired = 0
        for f in fields:
            ed = _value(f, "endDate")
            yr = re.search(r"(19|20)\d{2}", ed)
            if yr and int(yr.group(0)) < now.year:
                expired += 1
        return {
            "active": len(docs) - expired,
            "expired": expired,
            "avgValue": round(sum(nums) / len(nums), 2) if nums else None,
        }
    if doc_type == "medical":
        return {
            "patients": len({_value(f, "patient") for f in fields if _value(f, "patient")}),
            "facilities": len({_value(f, "facility") for f in fields if _value(f, "facility")}),
        }
    if doc_type == "report":
        return {
            "authors": len({_value(f, "author") for f in fields if _value(f, "author")}),
            "dateRange": _date_range(docs)["label"],
        }
    if doc_type == "id":
        issuers = len({_value(f, "issuer") for f in fields if _value(f, "issuer")})
        expiries = [_value(f, "expiryDate") for f in fields if _value(f, "expiryDate")]
        return {"issuers": issuers, "soonestExpiry": min(expiries) if expiries else None}
    return {"count": len(docs)}


def build_summary(all_docs: list[Document]) -> dict:
    done = [d for d in all_docs if d.status == "done"]
    pending = [d for d in all_docs if d.status in ("queued", "processing", "error")]
    type_counts = Counter(d.doc_type for d in done if d.doc_type)

    rows = []
    for d in done:
        label, value = key_field(d)
        rows.append(
            {
                "id": d.id,
                "filename": d.filename,
                "type": d.doc_type,
                "keyLabel": label,
                "keyField": value,
                "conf": conf_avg_label(d.fields or []),
                "status": d.status,
            }
        )

    subsections = {
        t: _subsection(t, [d for d in done if d.doc_type == t]) for t in type_counts
    }

    return {
        "totals": {"total": len(all_docs), "done": len(done), "pending": len(pending)},
        "typeCounts": dict(type_counts),
        "dateRange": _date_range(done),
        "rows": rows,
        "subsections": subsections,
        "deadlines": deadlines(done),
    }


def _doc_line(doc: Document) -> str:
    """One compact line: '- name [type]: Label=value, ...' over the doc's value fields."""
    pairs = [
        f"{f.get('label') or f.get('key')}={(f.get('value') or '').strip()}"
        for f in (doc.fields or [])
        if f.get("kind") == "value" and (f.get("value") or "").strip() not in ("", PLACEHOLDER)
    ]
    body = "; ".join(pairs) if pairs else "(no fields extracted)"
    return f"- {doc.filename} [{doc.doc_type or 'other'}]: {body}"


def build_corpus(all_docs: list[Document], cap: int = 200) -> str:
    """Compact text digest of the collection for the cross-document LLM Q&A.

    Header = aggregate stats (reuses build_summary); body = one line per done doc.
    Uses only extracted fields, so it stays small and scales to many documents."""
    done = [d for d in all_docs if d.status == "done"][:cap]
    summary = build_summary(all_docs)
    header = (
        f"Collection: {summary['totals']['done']} processed documents.\n"
        f"By type: {summary['typeCounts']}.\n"
        f"Date range: {summary['dateRange']['label']}.\n"
        f"Aggregates by type: {summary['subsections']}.\n"
    )
    lines = "\n".join(_doc_line(d) for d in done)
    return f"{header}\nDocuments:\n{lines}"
