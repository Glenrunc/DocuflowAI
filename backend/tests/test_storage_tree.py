"""On-disk folder tree: place() moves files into <Type>/<Category>/ and re-places on change."""

from pathlib import Path

import pytest

from app import storage_tree
from app.models import Document


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_tree.settings, "storage_dir", tmp_path)
    return tmp_path


def _doc(storage, name, doc_type, category_value=None, category_label=None):
    src = storage / name
    src.write_bytes(b"data")
    fields = []
    if category_value is not None:
        fields = [{
            "key": "category", "label": "Category", "icon": "x", "kind": "category",
            "value": category_value,
            "options": [{"value": category_value, "label": category_label or category_value, "color": "#000"}],
        }]
    return Document(filename=name, mime="image/jpeg", stored_path=str(src),
                    doc_type=doc_type, status="done", fields=fields)


def test_place_moves_into_type_category(storage):
    doc = _doc(storage, "a.jpg", "invoice", "meals", "Meals")
    storage_tree.place(doc)
    assert doc.stored_path == str(storage / "Invoice" / "Meals" / "a.jpg")
    assert Path(doc.stored_path).exists()
    assert not (storage / "a.jpg").exists()


def test_place_uncategorized_when_empty(storage):
    doc = _doc(storage, "b.jpg", "invoice", "")
    storage_tree.place(doc)
    assert doc.stored_path == str(storage / "Invoice" / "Uncategorized" / "b.jpg")


def test_place_no_category_level_for_typeless(storage):
    doc = _doc(storage, "c.jpg", "report")
    storage_tree.place(doc)
    assert doc.stored_path == str(storage / "Report" / "c.jpg")


def test_place_is_idempotent(storage):
    doc = _doc(storage, "d.jpg", "invoice", "meals", "Meals")
    storage_tree.place(doc)
    first = doc.stored_path
    storage_tree.place(doc)
    assert doc.stored_path == first
    assert Path(first).exists()


def test_place_collision_suffixes(storage):
    (storage / "Invoice" / "Meals").mkdir(parents=True)
    (storage / "Invoice" / "Meals" / "e.jpg").write_bytes(b"other")
    doc = _doc(storage, "e.jpg", "invoice", "meals", "Meals")
    storage_tree.place(doc)
    assert doc.stored_path.endswith(f"e-{doc.id[:6]}.jpg")


def test_place_reorganizes_on_type_change_and_prunes(storage):
    doc = _doc(storage, "f.jpg", "invoice", "meals", "Meals")
    storage_tree.place(doc)
    assert (storage / "Invoice" / "Meals").exists()
    # simulate change_type to contract (category reset → Uncategorized)
    doc.doc_type = "contract"
    doc.fields = [{"key": "contractType", "label": "Type", "icon": "x", "kind": "category", "value": "", "options": []}]
    storage_tree.place(doc)
    assert doc.stored_path == str(storage / "Contract" / "Uncategorized" / "f.jpg")
    assert not (storage / "Invoice").exists()  # old empty tree pruned
