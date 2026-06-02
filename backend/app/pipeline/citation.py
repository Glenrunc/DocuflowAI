"""Build a source citation by locating the LLM's quoted snippet in the document text (§9.1)."""

from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def build_citation(ocr_text: str, source: str) -> str | None:
    source = (source or "").strip()
    if not source:
        return None
    target = _norm(source)
    lines = ocr_text.splitlines()
    for i, line in enumerate(lines, start=1):
        if target and target in _norm(line):
            return f'Found on line {i}: "{line.strip()}"'
    # Snippet not found verbatim — still surface what the model cited.
    return f'Source: "{source}"'
