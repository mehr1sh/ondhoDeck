"""Keyword retrieval of liquidity-relevant excerpts, preserving page metadata.

Long documents (the BREIT prospectus is 600+ pages) are never sent whole to the
LLM. We split each page into paragraph-sized chunks, score them against a
weighted liquidity vocabulary, de-duplicate repeated boilerplate (the same
clause appears in several supplements) and return the top excerpts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .document_parser import ParsedDocument, normalize_text

# term -> weight. Multi-word phrases are worth more than single words.
SEARCH_TERMS: dict[str, float] = {
    "share repurchase plan": 4, "repurchase limitations": 5, "repurchase plan": 2,
    "aggregate nav": 4, "pro rata": 4, "per calendar quarter": 4, "calendar quarter": 2,
    "per month": 2, "monthly": 1, "repurchase fewer shares": 5, "or none at all": 4,
    "early repurchase deduction": 3, "resubmitted": 3, "suspend": 1,
    "repurchase offer": 4, "repurchase request deadline": 3, "repurchase fee": 3,
    "collateral": 2, "advance rate": 5, "loan-to-value": 5, "maintenance": 2,
    "collateral call": 5, "cure": 2, "capital call": 5, "drawdown notice": 4,
    "unfunded commitment": 3, "business days": 1, "withholding": 3,
    "supplemental wage": 4, "trading window": 5, "blackout": 3, "liquidity": 1,
    "settlement": 1,
    # suspension, demand and termination language
    "suspend or postpone": 4, "postpone": 2, "on demand": 4, "demand full or partial": 4,
    "sole discretion": 2, "terminate and cancel": 4,
    # private funds
    "capital contribution": 3, "capital commitment": 4, "defaulting partner": 4, "business days after": 2,
    # equity awards
    "vesting schedule": 5, "shall vest": 4, "vests": 2, "forfeit": 4, "termination of employment": 4,
    "termination of service": 4,
}

_MIN_CHUNK = 200
_MAX_CHUNK = 2200


@dataclass
class Excerpt:
    excerpt_id: str
    document_id: str
    document_name: str
    pdf_page: int
    printed_page: str | None
    text: str
    score: float
    matched_terms: list[str] = field(default_factory=list)
    duplicate_pages: list[int] = field(default_factory=list)


def _chunks(page_text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", page_text) if p.strip()]
    out: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) < _MAX_CHUNK:
            buf = f"{buf}\n\n{p}" if buf else p
            if len(buf) >= _MIN_CHUNK:
                out.append(buf)
                buf = ""
        else:
            if buf:
                out.append(buf)
            # split oversized paragraphs on sentence boundaries
            while len(p) > _MAX_CHUNK:
                cut = p.rfind(". ", 0, _MAX_CHUNK)
                cut = cut + 1 if cut > _MIN_CHUNK else _MAX_CHUNK
                out.append(p[:cut])
                p = p[cut:].strip()
            buf = p
    if buf:
        out.append(buf)
    return out


def score_text(text: str, terms: dict[str, float] = SEARCH_TERMS) -> tuple[float, list[str]]:
    low = normalize_text(text).lower()
    score, matched = 0.0, []
    for term, w in terms.items():
        n = low.count(term)
        if n:
            score += w * min(n, 3)
            matched.append(term)
    return score, matched


def retrieve_excerpts(doc: ParsedDocument, top_k: int = 8, min_score: float = 6.0,
                      terms: dict[str, float] = SEARCH_TERMS) -> list[Excerpt]:
    candidates: list[Excerpt] = []
    for page in doc.pages:
        for j, chunk in enumerate(_chunks(page.text)):
            s, matched = score_text(chunk, terms)
            if s >= min_score:
                candidates.append(Excerpt(
                    excerpt_id=f"p{page.pdf_page}-c{j}", document_id=doc.document_id,
                    document_name=doc.name, pdf_page=page.pdf_page,
                    printed_page=page.printed_page, text=chunk.strip(), score=s,
                    matched_terms=matched))
    # De-duplicate repeated boilerplate: keep the highest-scoring copy and record
    # the other pages where substantially the same text appears.
    candidates.sort(key=lambda e: (-e.score, e.pdf_page))
    kept: list[Excerpt] = []
    signatures: dict[str, Excerpt] = {}
    for c in candidates:
        sig = normalize_text(c.text).lower()[:160]
        if sig in signatures:
            signatures[sig].duplicate_pages.append(c.pdf_page)
            continue
        signatures[sig] = c
        kept.append(c)
    return kept[:top_k]
