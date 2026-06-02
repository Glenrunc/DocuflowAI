"""CSV export profiles — §13. Flat (universal) and Invoice (fixed columns)."""

from __future__ import annotations

import csv
import io

from .models import Document
from .summary_calc import _CONF_SCORE, _value


def _conf_avg(fields: list[dict]) -> float | str:
    scores = [_CONF_SCORE.get(f.get("confidence", ""), 0.33) for f in fields if f.get("kind") == "value"]
    return round(sum(scores) / len(scores), 2) if scores else ""


def export_flat(docs: list[Document]) -> str:
    value_fields = [[f for f in (d.fields or []) if f.get("kind") == "value"] for d in docs]
    max_fields = max((len(vf) for vf in value_fields), default=0)

    header = ["filename", "detected_type"]
    for i in range(1, max_fields + 1):
        header += [f"field_{i}_label", f"field_{i}_value"]
    header.append("confidence_avg")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for d, vf in zip(docs, value_fields):
        row = [d.filename, d.doc_type or ""]
        for f in vf:
            row += [f.get("label", ""), f.get("value", "")]
        row += [""] * ((max_fields - len(vf)) * 2)
        row.append(_conf_avg(d.fields or []))
        w.writerow(row)
    return buf.getvalue()


def export_invoice(docs: list[Document]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["filename", "date", "merchant", "total", "taxes", "category", "confidence_avg"])
    for d in docs:
        if d.doc_type != "invoice":
            continue
        f = d.fields or []
        w.writerow(
            [
                d.filename,
                _value(f, "date"),
                _value(f, "merchant"),
                _value(f, "total"),
                _value(f, "taxes"),
                _value(f, "category"),
                _conf_avg(f),
            ]
        )
    return buf.getvalue()
