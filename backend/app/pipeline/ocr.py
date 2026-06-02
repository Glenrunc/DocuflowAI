"""docTR OCR wrapper. Runs on GPU when available, falls back to CPU (degraded, logged).

Heavy deps (torch, doctr) are imported lazily so the API process and unit tests don't need them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

_predictor = None


@dataclass
class OcrWord:
    text: str
    bbox: list[float]  # [x%, y%, w%, h%] relative to its page
    page: int


@dataclass
class OcrResult:
    text: str
    words: list[OcrWord] = field(default_factory=list)
    page_count: int = 1


def _get_predictor():
    global _predictor
    if _predictor is not None:
        return _predictor

    import torch
    from doctr.models import ocr_predictor

    model = ocr_predictor(pretrained=True)
    use_cuda = settings.ocr_device == "cuda" and torch.cuda.is_available()
    if use_cuda:
        model = model.cuda()
    else:
        if settings.ocr_device == "cuda":
            logger.warning("CUDA requested but unavailable — running docTR on CPU (degraded).")
    _predictor = model
    return _predictor


def _load_pages(path: Path, mime: str):
    from doctr.io import DocumentFile

    suffix = path.suffix.lower()
    if suffix == ".pdf" or mime == "application/pdf":
        return DocumentFile.from_pdf(str(path))
    if suffix in (".heic", ".heif"):
        import pillow_heif
        from PIL import Image
        import numpy as np

        heif = pillow_heif.read_heif(str(path))
        img = Image.frombytes(heif.mode, heif.size, heif.data)
        return [np.array(img.convert("RGB"))]
    return DocumentFile.from_images(str(path))


def render_page1_png(path: Path, mime: str, out: Path) -> None:
    """Rasterize page 1 to PNG. Uses the same loader docTR uses, so the saved image
    matches the geometry the OCR bboxes were derived from (exact overlay alignment)."""
    from PIL import Image

    pages = _load_pages(path, mime)
    Image.fromarray(pages[0]).save(out)


def warmup() -> None:
    """Load the predictor and run one tiny inference so the first real doc isn't cold
    (weights load + CUDA kernel compile happen here, at worker start, not on user time)."""
    import numpy as np

    predictor = _get_predictor()
    predictor([np.zeros((32, 32, 3), dtype=np.uint8)])


def run_ocr(path: Path, mime: str) -> OcrResult:
    pages = _load_pages(path, mime)
    predictor = _get_predictor()
    result = predictor(pages)

    lines_text: list[str] = []
    words: list[OcrWord] = []
    for page_idx, page in enumerate(result.pages):
        for block in page.blocks:
            for line in block.lines:
                line_words = []
                for w in line.words:
                    (x0, y0), (x1, y1) = w.geometry
                    line_words.append(w.value)
                    words.append(
                        OcrWord(
                            text=w.value,
                            bbox=[
                                round(x0 * 100, 2),
                                round(y0 * 100, 2),
                                round((x1 - x0) * 100, 2),
                                round((y1 - y0) * 100, 2),
                            ],
                            page=page_idx,
                        )
                    )
                if line_words:
                    lines_text.append(" ".join(line_words))

    return OcrResult(text="\n".join(lines_text), words=words, page_count=len(result.pages))
