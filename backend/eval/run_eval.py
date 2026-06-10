"""Evaluation runner — measures the §6 table of livrables/protocole_evaluation.md.

Compares the DocuFlow LLM pipeline (classify + parse, needs Ollama) against the
deterministic regex/heuristic baseline (§4) on a labelled OCR-text sample set.

Data layout (one labelled set, held out from development):

    eval/data/labels.json    {"recu1.txt": {"type": "invoice",
                                            "fields": {"total": "RM 9.00", "date": "...",
                                                       "merchant": "...", "taxes": "..."}},
                              ...}
    eval/data/recu1.txt      raw OCR text of the document (one .txt per labelled doc)

Usage (from backend/, venv active):

    python -m eval.run_eval --data eval/data --baseline-only   # no Ollama needed
    python -m eval.run_eval --data eval/data                   # baseline + LLM (Ollama up)

Prints the §6 markdown table (accuracy per field, F1 macro type, LLM latency).
The bbox-derivation rate is measured in the running app (doc.stages), not here.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
from pathlib import Path

from app.pipeline.llm import _heuristic_type, classify_type
from app.pipeline.parse import parse_document_fields
from app.summary_calc import parse_money

MONEY_FIELDS = {"total", "taxes", "value"}
INVOICE_FIELDS = ["total", "date", "merchant", "taxes"]

_MONEY_RE = re.compile(r"-?\d+[ .,]?\d*[.,]\d{2}")
_DATE_RE = re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b")
_TOTAL_KEYWORDS = ("total", "amount", "due")
_TAX_KEYWORDS = ("gst", "sst", "tax", "tps", "tvq", "service charge")
_CORP_MARKERS = ("SDN BHD", "SDN. BHD", "LTD", "INC", "ENTERPRISE", "TRADING", "S/B")


def norm(field: str, value: str | None) -> str:
    """Exact-match normalization (§3): case, whitespace, money separators."""
    v = (value or "").strip()
    if field in MONEY_FIELDS:
        amt = parse_money(v)
        if amt is not None:
            return f"{amt:.2f}"
    return re.sub(r"\s+", " ", v).casefold()


def exact(field: str, pred: str | None, truth: str) -> bool:
    return norm(field, pred) == norm(field, truth)


def baseline_fields(text: str) -> dict[str, str]:
    """§4 deterministic baseline for invoice fields — regex/heuristics, no LLM."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out: dict[str, str] = {}

    def amounts_on(keywords: tuple[str, ...]) -> list[float]:
        return [
            amt
            for line in lines
            if any(k in line.lower() for k in keywords)
            for m in _MONEY_RE.finditer(line)
            if (amt := parse_money(m.group(0))) is not None
        ]

    totals = amounts_on(_TOTAL_KEYWORDS)
    if totals:
        out["total"] = f"{max(totals):.2f}"
    taxes = amounts_on(_TAX_KEYWORDS)
    if taxes:
        out["taxes"] = f"{max(taxes):.2f}"

    m = _DATE_RE.search(text)
    if m:
        out["date"] = m.group(0)

    for line in lines[:8]:  # merchant: first all-caps / corporate-marker header line
        up = line.upper()
        if any(mk in up for mk in _CORP_MARKERS) or (line == up and len(line) > 3
                                                     and any(c.isalpha() for c in line)):
            out["merchant"] = line
            break
    return out


def f1_macro(truths: list[str], preds: list[str]) -> float:
    classes = sorted(set(truths))
    scores = []
    for c in classes:
        tp = sum(1 for t, p in zip(truths, preds) if t == c and p == c)
        fp = sum(1 for t, p in zip(truths, preds) if t != c and p == c)
        fn = sum(1 for t, p in zip(truths, preds) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(scores) / len(scores)


def load_samples(data_dir: Path) -> list[dict]:
    labels = json.loads((data_dir / "labels.json").read_text())
    samples = []
    for fname, label in labels.items():
        samples.append({
            "name": fname,
            "ocr_text": (data_dir / fname).read_text(),
            "type": label["type"],
            "fields": label.get("fields", {}),
        })
    return samples


def evaluate(samples: list[dict], use_llm: bool) -> dict:
    per_field: dict[str, list[bool]] = {f: [] for f in INVOICE_FIELDS}
    type_truths, type_preds, latencies = [], [], []

    for s in samples:
        t0 = time.monotonic()
        if use_llm:
            pred_type = classify_type(s["ocr_text"])
            raw = parse_document_fields(pred_type, s["ocr_text"])
            pred_fields = {k: (v or {}).get("value", "") for k, v in raw.items()}
        else:
            pred_type = _heuristic_type(s["ocr_text"]) or "other"
            pred_fields = baseline_fields(s["ocr_text"]) if s["type"] == "invoice" else {}
        latencies.append(time.monotonic() - t0)

        type_truths.append(s["type"])
        type_preds.append(pred_type)
        for field, truth in s["fields"].items():
            if field in per_field:
                per_field[field].append(exact(field, pred_fields.get(field), truth))

    return {
        "accuracy": {f: (sum(v) / len(v) if v else None) for f, v in per_field.items()},
        "f1_macro": f1_macro(type_truths, type_preds),
        "latency_median": statistics.median(latencies),
        "latency_p95": sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)],
    }


def fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument("--baseline-only", action="store_true",
                    help="skip the LLM pipeline (no Ollama required)")
    args = ap.parse_args()

    samples = load_samples(args.data)
    print(f"{len(samples)} labelled samples from {args.data}\n")

    base = evaluate(samples, use_llm=False)
    llm = evaluate(samples, use_llm=True) if not args.baseline_only else None

    print("| Métrique | Baseline (regex) | DocuFlow (LLM) | Gain |")
    print("|---|---|---|---|")
    for f in INVOICE_FIELDS:
        b, l = base["accuracy"][f], llm["accuracy"][f] if llm else None
        gain = f"{l - b:+.2f}" if llm and b is not None and l is not None else ""
        print(f"| Accuracy `{f}` (invoice) | {fmt(b)} | {fmt(l) if llm else ''} | {gain} |")
    gain = f"{llm['f1_macro'] - base['f1_macro']:+.2f}" if llm else ""
    print(f"| F1 macro classification type | {base['f1_macro']:.2f} | "
          f"{f'{llm['f1_macro']:.2f}' if llm else ''} | {gain} |")
    if llm:
        print(f"| Latence médiane / doc (s) | — | {llm['latency_median']:.1f} | |")
        print(f"| Latence p95 / doc (s) | — | {llm['latency_p95']:.1f} | |")


if __name__ == "__main__":
    main()
