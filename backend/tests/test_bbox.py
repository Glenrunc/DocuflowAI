"""bbox derivation: match extracted value against docTR word geometry (pipeline.bbox)."""

from app.pipeline.bbox import derive_bbox
from app.pipeline.ocr import OcrWord


def _words():
    # A small synthetic page: "Café Urbain ... $47.85"
    return [
        OcrWord(text="Café", bbox=[10.0, 8.0, 9.0, 4.0], page=0),
        OcrWord(text="Urbain", bbox=[20.0, 8.0, 9.0, 4.0], page=0),
        OcrWord(text="Total", bbox=[55.0, 72.0, 7.0, 4.0], page=0),
        OcrWord(text="$47.85", bbox=[64.0, 72.0, 12.0, 4.0], page=0),
    ]


def test_multi_word_value_unions_windows():
    box = derive_bbox("Café Urbain", _words())
    assert box == [10.0, 8.0, 19.0, 4.0]


def test_single_token_value():
    box = derive_bbox("$47.85", _words())
    assert box == [64.0, 72.0, 12.0, 4.0]


def test_no_match_returns_none():
    assert derive_bbox("zzzzz", _words()) is None


def test_empty_value_returns_none():
    assert derive_bbox("", _words()) is None


def test_page_filter_excludes_other_pages():
    words = [OcrWord(text="$47.85", bbox=[64.0, 72.0, 12.0, 4.0], page=1)]
    assert derive_bbox("$47.85", words, page=0) is None
    assert derive_bbox("$47.85", words, page=1) == [64.0, 72.0, 12.0, 4.0]
