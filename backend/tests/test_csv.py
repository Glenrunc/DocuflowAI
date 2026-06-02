"""CSV export profiles — flat (universal) and invoice (fixed columns) (csv_export)."""

import csv
import io

from app.csv_export import export_flat, export_invoice
from app.models import Document


def _doc(filename, doc_type, fields):
    return Document(filename=filename, mime="application/pdf", stored_path="/x", doc_type=doc_type, fields=fields)


def _invoice_fields():
    return [
        {"key": "date", "label": "Date", "kind": "value", "value": "2024-11-03", "confidence": "high"},
        {"key": "merchant", "label": "Merchant", "kind": "value", "value": "Café Urbain", "confidence": "high"},
        {"key": "total", "label": "Total", "kind": "value", "value": "$47.85", "confidence": "med"},
        {"key": "taxes", "label": "Taxes", "kind": "value", "value": "$6.24", "confidence": "low"},
        {"key": "category", "label": "Category", "kind": "category", "value": "meals", "confidence": "high"},
    ]


def test_flat_header_and_row():
    docs = [_doc("a.pdf", "invoice", _invoice_fields())]
    rows = list(csv.reader(io.StringIO(export_flat(docs))))
    header, row = rows[0], rows[1]
    assert header[0] == "filename"
    assert header[1] == "detected_type"
    assert header[-1] == "confidence_avg"
    assert row[0] == "a.pdf"
    assert row[1] == "invoice"
    # category is not a value field → excluded from flat field pairs
    assert "Café Urbain" in row


def test_flat_pads_shorter_rows():
    docs = [
        _doc("a.pdf", "invoice", _invoice_fields()),
        _doc("b.pdf", "other", [{"key": "x", "label": "X", "kind": "value", "value": "1", "confidence": "high"}]),
    ]
    rows = list(csv.reader(io.StringIO(export_flat(docs))))
    assert len({len(r) for r in rows}) == 1  # all rows same width


def test_invoice_profile_only_invoices_fixed_columns():
    docs = [
        _doc("a.pdf", "invoice", _invoice_fields()),
        _doc("b.pdf", "contract", []),
    ]
    rows = list(csv.reader(io.StringIO(export_invoice(docs))))
    assert rows[0] == ["filename", "date", "merchant", "total", "taxes", "category", "confidence_avg"]
    assert len(rows) == 2  # header + 1 invoice (contract skipped)
    assert rows[1][2] == "Café Urbain"
