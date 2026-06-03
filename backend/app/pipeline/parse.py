from .llm import parse_fields


def parse_document_fields(doc_type: str, ocr_text: str, category_choices: dict | None = None) -> dict:
    """Raw {key: {value, confidence}} mapping from the LLM, ready for schema validation."""
    return parse_fields(doc_type, ocr_text, category_choices).get("fields", {})
