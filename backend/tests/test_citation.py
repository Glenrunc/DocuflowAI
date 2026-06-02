"""Citation building — locate the LLM's quoted snippet in the OCR text (pipeline.citation)."""

from app.pipeline.citation import build_citation

OCR = "Invoice #4521\nCafé Urbain\nTotal due: $47.85\nThank you"


def test_match_returns_line_number():
    assert build_citation(OCR, "Total due: $47.85") == 'Found on line 3: "Total due: $47.85"'


def test_match_is_whitespace_insensitive():
    assert build_citation(OCR, "total   due:  $47.85") == 'Found on line 3: "Total due: $47.85"'


def test_unmatched_snippet_falls_back_to_source():
    assert build_citation(OCR, "not present") == 'Source: "not present"'


def test_empty_source_returns_none():
    assert build_citation(OCR, "") is None
    assert build_citation(OCR, "   ") is None
