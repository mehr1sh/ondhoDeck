#!/usr/bin/env python3
"""Validate the curated evaluation cases and extraction examples against the extracted source text,
then emit data/evaluation/expected_rules.jsonl in the common contract-rule schema.

Every clause_text is re-checked verbatim (whitespace and quote characters normalised) against the
cited PDF page of data/interim/extracted_text/<document_id>/pages.jsonl. Cases whose quote is not
found are emitted with verification_status = "quote_not_found" instead of being trusted.

Run scripts/prepare_contract_data.py first.

    .venv/bin/python scripts/build_evaluation_set.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "backend"))

from app.engine.document_parser import normalize_text  # noqa: E402

SCHEMA = json.loads((DATA / "schemas" / "contract_rule.schema.json").read_text())


def page_text(doc_id: str, page: int, cache: dict) -> str | None:
    if doc_id not in cache:
        path = DATA / "interim" / "extracted_text" / doc_id / "pages.jsonl"
        if not path.exists():
            cache[doc_id] = None
        else:
            cache[doc_id] = {json.loads(line)["pdf_page"]: json.loads(line)["text"] for line in path.open()}
    pages = cache[doc_id]
    return None if pages is None else pages.get(page)


def quote_on_page(quote: str, text: str | None) -> str:
    if text is None:
        return "page_text_missing"
    q, t = normalize_text(quote), normalize_text(text)
    if q in t:
        return "exact"
    if q.lower() in t.lower():
        return "case_insensitive"
    return "not_found"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def main() -> int:
    cache: dict = {}
    cases = read_jsonl(DATA / "labels" / "evaluation_cases.jsonl")
    examples = read_jsonl(DATA / "labels" / "extraction_examples.jsonl")
    results, rules = [], []
    for c in cases:
        match = quote_on_page(c["clause_text"], page_text(c["document_id"], c["source_page"], cache))
        ok = match in ("exact", "case_insensitive")
        rule = {
            "rule_id": f"{c['document_id']}:{c['expected_constraint_type']}:{c['case_id']}",
            "document_id": c["document_id"], "constraint_type": c["expected_constraint_type"],
            "clause_text": c["clause_text"], "source_page": c["source_page"], "printed_page": c["printed_page"],
            "source_section": c["source_section"], "value": c["expected_value"],
            "lower_bound": c["expected_lower_bound"], "upper_bound": c["expected_upper_bound"],
            "unit": c["expected_unit"], "value_kind": c["expected_value_kind"],
            "conditions": c["expected_conditions"], "exceptions": c["expected_exceptions"],
            "discretion": c["expected_discretion"], "effective_period": c["expected_effective_period"],
            "source_type": c["source_type"],
            "verification_status": c["verification_status"] if ok else "quote_not_found",
            "extraction_method": "manual",
            "reviewer_notes": f"{c['review_basis']} Script quote check: {match}. {c['notes']}".strip(),
        }
        jsonschema.validate(rule, SCHEMA)
        rules.append(rule)
        results.append(("case", c["case_id"], c["document_id"], c["source_page"], match))
    for e in examples:
        match = quote_on_page(e["clause_text"], page_text(e["document_id"], e["source_page"], cache))
        results.append(("example", e["example_id"], e["document_id"], e["source_page"], match))
    out = DATA / "evaluation" / "expected_rules.jsonl"
    with out.open("w") as fh:
        for r in rules:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (DATA / "evaluation" / "quote_checks.json").write_text(json.dumps(
        [{"kind": k, "id": i, "document_id": d, "source_page": p, "quote_check": m} for k, i, d, p, m in results],
        indent=2))
    bad = [r for r in results if r[4] not in ("exact", "case_insensitive")]
    for k, i, d, p, m in results:
        print(f"{k:8s} {i:22s} {d:32s} p{p:<4} {m}")
    print(f"\n{len(results) - len(bad)}/{len(results)} quotes found on their cited page; wrote {len(rules)} rules to {out.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
