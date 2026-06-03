"""Tests for the embedding/chunking module."""

from app.pipeline.embed import _chunk_text, cosine_similarity


def test_chunk_single_page():
    text = "word " * 100
    chunks = _chunk_text(text.strip(), page_count=1)
    assert len(chunks) == 1
    assert chunks[0]["page"] == 0


def test_chunk_multi_page():
    pages = ["Page one content here.\n" * 10, "Page two content here.\n" * 10]
    text = "\f".join(pages)
    chunks = _chunk_text(text, page_count=2)
    assert len(chunks) == 2
    assert chunks[0]["page"] == 0
    assert chunks[1]["page"] == 1


def test_chunk_long_page():
    text = " ".join(f"word{i}" for i in range(800))
    chunks = _chunk_text(text, page_count=1)
    assert len(chunks) >= 2
    assert all(c["page"] == 0 for c in chunks)


def test_cosine_identical():
    v = [1.0, 0.0, 0.5]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-6


def test_cosine_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(cosine_similarity(a, b) + 1.0) < 1e-6
