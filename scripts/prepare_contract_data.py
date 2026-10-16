#!/usr/bin/env python3
"""Extract page-preserving text and candidate clauses from the contracts listed in data/manifest.csv.

Outputs (all regenerable):
  data/interim/extracted_text/<document_id>/pages.jsonl      one record per PDF page (text, printed page, section)
  data/interim/extracted_text/<document_id>/full_text.txt    readable text with page markers
  data/interim/extracted_text/<document_id>/summary.json     page counts, blank/image-only pages, OCR need
  data/processed/contract_clauses/<document_id>.candidates.jsonl
        keyword-retrieved sentences that MAY state a rule - not rules, status candidate_unreviewed
  data/processed/contract_clauses/<document_id>.auto_rules.jsonl
        deterministic rule-based extraction (backend/app/engine) mapped to data/schemas/contract_rule.schema.json,
        always verification_status = "unverified"
and updates the extraction_status column of data/manifest.csv.

No LLM is used. Original files are only read.

    .venv/bin/python scripts/prepare_contract_data.py [--only DOCUMENT_ID ...]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "backend"))

from app.engine.constraint_extractor import extract_rule_based  # noqa: E402
from app.engine.document_parser import detect_printed_page, detect_section, normalize_text, parse_pdf  # noqa: E402

TEXT_DIR = DATA / "interim" / "extracted_text"
CLAUSE_DIR = DATA / "processed" / "contract_clauses"
MANIFEST = DATA / "manifest.csv"

# Engine constraint types -> common schema (constraint_type, value_kind, effective_period)
ENGINE_MAP = {
    "redemption_monthly_cap": ("redemption_limit", "maximum", "per calendar month"),
    "redemption_quarterly_cap": ("redemption_limit", "maximum", "per calendar quarter"),
    "pro_rata_fulfillment": ("pro_rata_fulfillment", "qualitative", None),
    "board_discretion": ("redemption_suspension", "qualitative", None),
    "resubmission_required": ("redemption_resubmission", "qualitative", None),
    "early_redemption_deduction": ("redemption_fee", "exact", None),
    "settlement_timing": ("redemption_settlement_timing", "maximum", None),
    "repurchase_offer_size": ("redemption_limit", "exact", "per quarterly repurchase offer"),
    "repurchase_offer_frequency": ("redemption_offer_frequency", "qualitative", None),
    "repurchase_fee": ("redemption_fee", "exact", None),
    "payment_timing": ("redemption_settlement_timing", "maximum", None),
    "sbl_advance_rate": ("collateral_advance_rate", "maximum", None),
    "sbl_maintenance_threshold": ("collateral_maintenance_threshold", "exact", None),
    "sbl_cure_period": ("margin_call_cure_period", "maximum", None),
    "sbl_interest_rate": ("interest_rate", "exact", "per annum"),
    "capital_call_notice": ("capital_call_deadline", "minimum", None),
    "capital_call_schedule": ("capital_commitment", "qualitative", None),
    "default_penalty": ("capital_call_default", "exact", "per annum"),
    "rsu_withholding_rate": ("tax_withholding", "exact", "at vest"),
    "rsu_max_withholding_rate": ("tax_withholding", "maximum", "at vest"),
    "trading_window": ("trading_window", "qualitative", None),
}

# Keyword families for candidate retrieval (case-insensitive). Candidates are for human review only.
CANDIDATE_PATTERNS: dict[str, str] = {
    "redemption_limit": r"(repurchas|redeem|redemption|tender)[^.]{0,160}(no more than|not (to )?exceed|up to|limited to|at least)[^.]{0,80}\d+(\.\d+)?\s?%",
    "redemption_offer_frequency": r"(quarterly|semi-annual|annual|monthly) (repurchase|tender) offers?",
    "redemption_notice_period": r"repurchase request deadline|notice of (the )?repurchase offer|tender[^.]{0,40}(deadline|notice)",
    "redemption_settlement_timing": r"(payment|pay|settle)[^.]{0,100}(within|no later than) [\w-]+ (business |calendar )?days",
    "pro_rata_fulfillment": r"pro[ -]rata",
    "redemption_suspension": r"(suspend|postpone)[^.]{0,100}(repurchase|redemption|offer)|(repurchase|redemption|offer)[^.]{0,100}(suspend|postpone)",
    "redemption_fee": r"(repurchase|redemption) (fee|deduction)|early repurchase deduction",
    "collateral_advance_rate": r"advance rate|lending value|loan value",
    "collateral_maintenance_threshold": r"maintenance (requirement|level|threshold|percentage)|collateral call|margin call|additional collateral",
    "margin_call_cure_period": r"cure period|(within|no later than) [\w-]+ (business )?days[^.]{0,120}(collateral|deposit|deficien)",
    "demand_repayment": r"(payable|repayable) (up)?on demand|demand (for )?(repayment|payment)|at any time[^.]{0,60}(demand|terminate)",
    "interest_rate": r"interest[^.]{0,60}(rate|per annum|libor|sofr|prime)",
    "capital_call_deadline": r"(capital call|drawdown|capital contribution)[^.]{0,160}(\d+|[a-z]+) (\(\d+\) )?(business )?days",
    "capital_commitment": r"(capital )?commitment[^.]{0,80}(\$|\d)",
    "capital_call_default": r"default(ing)? (limited )?partner|failure to (make|fund)[^.]{0,40}(contribution|capital call)",
    "vesting_schedule": r"\bvest(s|ing|ed)?\b[^.]{0,120}(\d|anniversar|date)",
    "tax_withholding": r"withh?old(ing)?[^.]{0,60}tax|tax[^.]{0,60}withh?old",
    "trading_window": r"trading window|blackout period",
    "termination_condition": r"terminat(e|ion)[^.]{0,100}(agreement|partnership|credit line|line|plan|offer)",
}
MAX_CANDIDATES_PER_TYPE = 25


def split_sentences(text: str) -> list[str]:
    flat = normalize_text(text)
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(\"“])", flat)
    return [p.strip() for p in parts if 30 <= len(p.strip()) <= 1500]


def read_manifest() -> list[dict]:
    with MANIFEST.open(newline="") as fh:
        return list(csv.DictReader(fh))


def write_manifest(rows: list[dict]) -> None:
    with MANIFEST.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def extract_pages(path: Path) -> tuple[list[dict], dict]:
    pages: list[dict] = []
    image_only, blank, failed = [], [], []
    section = None
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf):
            n = i + 1
            try:
                text = page.get_text("text")
            except Exception as exc:  # recorded, never silently dropped
                failed.append({"pdf_page": n, "error": type(exc).__name__})
                continue
            has_text = bool(text.strip())
            images = len(page.get_images())
            if not has_text:
                (image_only if images else blank).append(n)
            section = (detect_section(text) or section) if has_text else section
            pages.append({"pdf_page": n, "printed_page": detect_printed_page(text) if has_text else None,
                          "section": section, "has_text_layer": has_text, "image_count": images,
                          "char_count": len(text), "text": text})
        total = pdf.page_count
    summary = {"pages_total": total, "pages_with_text": sum(p["has_text_layer"] for p in pages),
               "blank_pages_no_images": blank, "image_only_pages_ocr_candidates": image_only,
               "failed_pages": failed, "ocr_required": bool(image_only) or not any(p["has_text_layer"] for p in pages)}
    return pages, summary


def candidates_for(doc_id: str, pages: list[dict]) -> list[dict]:
    out: list[dict] = []
    counts: dict[str, int] = {}
    compiled = {k: re.compile(v, re.I) for k, v in CANDIDATE_PATTERNS.items()}
    for p in pages:
        if not p["has_text_layer"]:
            continue
        for sent in split_sentences(p["text"]):
            types = [k for k, rx in compiled.items() if rx.search(sent) and counts.get(k, 0) < MAX_CANDIDATES_PER_TYPE]
            if not types:
                continue
            for k in types:
                counts[k] = counts.get(k, 0) + 1
            out.append({"candidate_id": f"{doc_id}:cand:{len(out) + 1}", "document_id": doc_id,
                        "candidate_types": types, "clause_text": sent, "source_page": p["pdf_page"],
                        "printed_page": p["printed_page"], "source_section": p["section"],
                        "status": "candidate_unreviewed",
                        "note": "Keyword match only. Not a rule; values must be read from the source by a reviewer."})
    return out


def auto_rules_for(doc_id: str, path: Path, source_type: str) -> list[dict]:
    report = extract_rule_based(parse_pdf(path))
    rules = []
    for i, c in enumerate(report.constraints, start=1):
        ctype, kind, period = ENGINE_MAP.get(c.constraint_type.value, ("other", "qualitative", None))
        if c.value is None and c.lower_bound is None and c.upper_bound is None:
            kind = "qualitative"
        conditions = [c.conditions] if c.conditions else []
        discretion = None
        if c.constraint_type.value == "board_discretion":
            discretion = "Board may repurchase fewer shares than requested, or none, and may modify or suspend the plan."
        rules.append({
            "rule_id": f"{doc_id}:{ctype}:{i}", "document_id": doc_id, "constraint_type": ctype,
            "clause_text": c.evidence_quote, "source_page": c.pdf_page, "printed_page": c.printed_page,
            "source_section": c.document_section, "value": c.value, "lower_bound": c.lower_bound,
            "upper_bound": c.upper_bound, "unit": c.unit, "value_kind": kind, "conditions": conditions,
            "exceptions": [], "discretion": discretion, "effective_period": period or c.timing,
            "source_type": "synthetic" if source_type == "synthetic" else "real_public",
            "verification_status": "unverified", "extraction_method": "rule_based",
            "reviewer_notes": ("Automatic extraction. Quote found verbatim on the cited page by the extractor."
                               if c.quote_verified else "Automatic extraction. Quote NOT found verbatim - check."),
        })
    return rules


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="document_ids to process (default: all contracts in the manifest)")
    args = ap.parse_args()
    rows = read_manifest()
    for row in rows:
        if row["data_category"] != "contract" or (args.only and row["document_id"] not in args.only):
            continue
        doc_id = row["document_id"]
        if not row["relative_path"] or not (ROOT / row["relative_path"]).exists():
            row["extraction_status"] = "missing"
            print(f"{doc_id:32s} missing")
            continue
        path = ROOT / row["relative_path"]
        try:
            pages, summary = extract_pages(path)
        except Exception as exc:
            row["extraction_status"] = f"failed: {type(exc).__name__}"
            print(f"{doc_id:32s} FAILED {exc}")
            continue
        out = TEXT_DIR / doc_id
        write_jsonl(out / "pages.jsonl", pages)
        with (out / "full_text.txt").open("w") as fh:
            for p in pages:
                label = f" | printed p. {p['printed_page']}" if p["printed_page"] else ""
                fh.write(f"\n===== [pdf page {p['pdf_page']}{label}] =====\n{p['text']}")
        summary.update({"document_id": doc_id, "source_file": row["relative_path"], "source_url": row["source_url"] or None})
        cands = candidates_for(doc_id, pages)
        rules = auto_rules_for(doc_id, path, row["source_type"])
        summary.update({"candidate_passages": len(cands), "auto_rules": len(rules)})
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        write_jsonl(CLAUSE_DIR / f"{doc_id}.candidates.jsonl", cands)
        write_jsonl(CLAUSE_DIR / f"{doc_id}.auto_rules.jsonl", rules)
        if summary["failed_pages"]:
            status = f"partial: {len(summary['failed_pages'])} page(s) failed"
        elif summary["ocr_required"]:
            status = f"ocr_required: {len(summary['image_only_pages_ocr_candidates'])} image-only page(s)"
        else:
            status = "text_extracted"
        row["extraction_status"] = status
        print(f"{doc_id:32s} {status:24s} pages={summary['pages_total']:4d} blank={len(summary['blank_pages_no_images'])} "
              f"candidates={len(cands):3d} auto_rules={len(rules)}")
    write_manifest(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
