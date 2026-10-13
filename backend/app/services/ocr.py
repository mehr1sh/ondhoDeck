"""OCR fallback for pages without a text layer (scanned documents)."""
from __future__ import annotations

import io
import logging
import shutil
from dataclasses import dataclass, field

import pymupdf

log = logging.getLogger("slipslopes.ocr")


@dataclass
class OcrResult:
    available: bool
    texts: dict[int, str] = field(default_factory=dict)  # pdf_page (1-based) -> text
    failed: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)     # beyond the page budget


def ocr_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_pages(data: bytes, pages: list[int], max_pages: int, dpi: int = 200) -> OcrResult:
    if not pages:
        return OcrResult(available=ocr_available())
    if not ocr_available():
        return OcrResult(available=False, failed=list(pages))
    import pytesseract
    from PIL import Image

    result = OcrResult(available=True, skipped=pages[max_pages:])
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for n in pages[:max_pages]:
            try:
                pix = pdf.load_page(n - 1).get_pixmap(dpi=dpi)
                text = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), timeout=60)
            except Exception as exc:  # tesseract errors/timeouts
                log.warning("OCR failed on page %s: %s", n, type(exc).__name__)
                result.failed.append(n)
                continue
            if text.strip():
                result.texts[n] = text
            else:
                result.failed.append(n)
    return result
