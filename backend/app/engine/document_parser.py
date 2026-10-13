"""Page-by-page PDF text extraction with PDF-page -> printed-page mapping."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

# Standalone page labels as printed in footers/headers: "89", "S-3", "F-12", "A-1", "ii".
_PRINTED_PAGE_RE = re.compile(r"^(?:[A-Z]{1,2}-\d{1,4}|\d{1,4}|[ivxlc]{1,7})$")


@dataclass
class PageText:
    pdf_page: int  # 1-indexed physical page
    text: str
    printed_page: str | None = None
    section: str | None = None  # e.g. "Supplement No. 5 (August 17, 2026)" or "Base prospectus"


_SUPPLEMENT_RE = re.compile(r"SUPPLEMENT NO\. (\d+) DATED ([A-Z]+ \d{1,2}, \d{4})")
_BASE_PROSPECTUS_RE = re.compile(r"^.{0,120}\n?Maximum Offering of", re.S)


def detect_section(text: str) -> str | None:
    """Detect the start of a prospectus supplement or of the base prospectus on a page."""
    head = text[:400]
    m = _SUPPLEMENT_RE.search(head)
    if m:
        return f"Supplement No. {m.group(1)} ({m.group(2).title()})"
    if _BASE_PROSPECTUS_RE.search(text[:300]):
        return "Base prospectus"
    return None


@dataclass
class ParsedDocument:
    document_id: str
    name: str
    pages: list[PageText] = field(default_factory=list)
    failed_pages: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages) + len(self.failed_pages)

    def page(self, pdf_page: int) -> PageText | None:
        for p in self.pages:
            if p.pdf_page == pdf_page:
                return p
        return None


def normalize_text(s: str) -> str:
    """Canonical form for quote matching: straight quotes, no hyphen breaks, single spaces."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace(" ", " ")
    for lig, plain in (("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl")):
        s = s.replace(lig, plain)
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)  # de-hyphenate line breaks
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def detect_printed_page(text: str) -> str | None:
    """Look for a standalone page label in the last (then first) few lines of a page."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    for ln in list(reversed(lines[-4:])) + lines[:2]:
        if _PRINTED_PAGE_RE.match(ln) and not re.fullmatch(r"(19|20)\d\d", ln):
            return ln
    return None


def document_id_for(data: bytes, name: str) -> str:
    return f"{Path(name).stem[:24]}-{hashlib.sha1(data).hexdigest()[:8]}"


def parse_pdf_bytes(data: bytes, name: str) -> ParsedDocument:
    doc_id = document_id_for(data, name)
    parsed = ParsedDocument(document_id=doc_id, name=name)
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # corrupt / not a PDF
        parsed.errors.append(f"Could not open PDF: {exc}")
        return parsed
    section: str | None = None
    with pdf:
        for i in range(pdf.page_count):
            try:
                text = pdf.load_page(i).get_text("text")
            except Exception as exc:
                parsed.failed_pages.append(i + 1)
                parsed.errors.append(f"Page {i + 1}: text extraction failed ({exc})")
                continue
            if not text.strip():
                # Likely a scanned/image page; keep a record so the UI can report it.
                parsed.failed_pages.append(i + 1)
                continue
            section = detect_section(text) or section
            parsed.pages.append(PageText(pdf_page=i + 1, text=text, printed_page=detect_printed_page(text),
                                         section=section))
    return parsed


def parse_pdf(path: str | Path) -> ParsedDocument:
    path = Path(path)
    return parse_pdf_bytes(path.read_bytes(), path.name)
