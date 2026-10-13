"""Upload validation: size, type, structure. Runs before anything is stored."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pymupdf

from ..config import Settings
from ..errors import ApiError


@dataclass
class ValidatedPdf:
    sha256: str
    size_bytes: int
    page_count: int


def validate_pdf(data: bytes, settings: Settings) -> ValidatedPdf:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if not data:
        raise ApiError(422, "unprocessable", "The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ApiError(413, "payload_too_large", f"Files must be {settings.max_upload_mb} MB or smaller.")
    # Magic bytes: a PDF header must appear at the start (some writers prefix a few bytes).
    if b"%PDF-" not in data[:1024]:
        raise ApiError(415, "unsupported_media_type", "Only PDF documents are accepted.")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass or pdf.is_encrypted:
                raise ApiError(422, "unprocessable", "Password-protected PDFs are not supported.")
            pages = pdf.page_count
    except ApiError:
        raise
    except Exception as exc:  # malformed / hostile file: never echo parser internals
        raise ApiError(422, "unprocessable", "The file could not be read as a PDF.") from exc
    if pages < 1:
        raise ApiError(422, "unprocessable", "The PDF has no pages.")
    if pages > settings.max_pdf_pages:
        raise ApiError(422, "unprocessable", f"PDFs are limited to {settings.max_pdf_pages} pages.")
    return ValidatedPdf(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), page_count=pages)
