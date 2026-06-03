"""Discovered-but-stable categories: slugify, known_categories merge, resolve_categories."""

from app.categories import known_categories, resolve_categories, slugify, _color
from app.models import Document
from app.schema_def import validate_fields


def test_slugify():
    assert slugify("Food & Drink") == "food_drink"
    assert slugify("  Meals  ") == "meals"
    assert slugify("") == ""
    assert slugify(None) == ""


def test_color_is_deterministic():
    assert _color("groceries") == _color("groceries")


def _invoice_doc(category_value: str) -> Document:
    fields = [vf.model_dump(exclude_none=True) for vf in validate_fields("invoice", {})]
    for f in fields:
        if f["kind"] == "category":
            f["value"] = category_value
    return Document(filename="r.jpg", mime="image/jpeg", stored_path="/tmp/r.jpg",
                    doc_type="invoice", status="done", fields=fields)


def test_known_categories_includes_schema_seeds(session):
    values = {o.value for o in known_categories(session, "invoice")}
    assert {"meals", "transport", "office"} <= values


def test_known_categories_picks_up_seen_value(session):
    session.add(_invoice_doc("groceries"))
    session.commit()
    values = {o.value for o in known_categories(session, "invoice")}
    assert "groceries" in values


def test_resolve_reuses_existing_category(session):
    fields = validate_fields("invoice", {})
    resolve_categories(session, "invoice", fields, {"category": {"value": "Meals"}})
    cat = next(f for f in fields if f.kind == "category")
    assert cat.value == "meals"  # slug of an existing seed
    assert any(o.value == "meals" for o in cat.options)


def test_resolve_discovers_new_category(session):
    fields = validate_fields("invoice", {})
    resolve_categories(session, "invoice", fields, {"category": {"value": "Pet Supplies"}})
    cat = next(f for f in fields if f.kind == "category")
    assert cat.value == "pet_supplies"
    opt = next(o for o in cat.options if o.value == "pet_supplies")
    assert opt.label == "Pet Supplies" and opt.color.startswith("#")


def test_resolve_empty_value_is_uncategorized(session):
    fields = validate_fields("invoice", {})
    resolve_categories(session, "invoice", fields, {})
    cat = next(f for f in fields if f.kind == "category")
    assert cat.value == ""
    assert cat.options  # full known set still attached for the dropdown
