"""Evaluate contract-term extraction against the source-checked reference rules.

Reference labels: data/evaluation/expected_rules.jsonl (manually read against the cited page during
dataset preparation; pending human sign-off). They are NOT model predictions. The set is small (19
rules, 5 real documents) and not exhaustive, so predictions without a matching reference rule are
reported as "unmatched", not as errors.

Extractors:
  rule_based  - always run (deterministic, no network, no cost).
  llm         - run only when EVAL_LLM_PROVIDER is set to anthropic|openai and the matching
                ANTHROPIC_API_KEY / OPENAI_API_KEY (and EVAL_LLM_MODEL for openai) are in the environment.
                Keys are read from the environment only and are never written to the report.

Usage:
  .venv/bin/python scripts/evaluate_extraction.py [--out data/evaluation]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine.constraint_extractor import extract_rule_based, extract_with_llm, verify_quote  # noqa: E402
from app.engine.document_parser import ParsedDocument, normalize_text, parse_pdf  # noqa: E402
from app.engine.retrieval import retrieve_excerpts  # noqa: E402
from app.engine.schemas import ContractConstraint  # noqa: E402

EXPECTED = ROOT / "data/evaluation/expected_rules.jsonl"
MANIFEST = ROOT / "data/manifest.csv"

# Reference-label vocabulary -> engine constraint types that express the same contractual term.
TYPE_MAP: dict[str, set[str]] = {
    "redemption_limit": {"redemption_monthly_cap", "redemption_quarterly_cap", "repurchase_offer_size"},
    "pro_rata_fulfillment": {"pro_rata_fulfillment"},
    "redemption_suspension": {"redemption_suspension", "board_discretion"},
    "redemption_fee": {"early_redemption_deduction", "repurchase_fee"},
    "redemption_settlement_timing": {"settlement_timing", "payment_timing"},
    "demand_repayment": {"demand_repayment"},
    "collateral_maintenance_threshold": {"sbl_maintenance_threshold"},
    "termination_condition": {"termination_condition"},
    "capital_call_deadline": {"capital_call_notice"},
    "capital_commitment": {"capital_commitment"},
    "capital_call_default": {"default_penalty"},
}
# Documents the rule patterns were written against: rule-based scores there are not held-out.
DEVELOPMENT_DOCS = {"contract_breit_001"}

_WORD = re.compile(r"[a-z0-9%]+")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(s: str) -> set[str]:
    return set(_WORD.findall(normalize_text(s).lower()))


def overlap(a: str, b: str) -> float:
    """Share of the shorter text's tokens found in the longer one."""
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0


def unit_family(u: str | None) -> str | None:
    if not u:
        return None
    u = u.lower()
    if "%" in u or "percent" in u:
        return "percent"
    if "business day" in u:
        return "business_days"
    if "day" in u:
        return "calendar_days"
    if "month" in u:
        return "months"
    return u.strip()


def location_ok(pred: ContractConstraint, exp: dict, doc: ParsedDocument) -> bool:
    """The prediction points at the reference clause: same page, the reference clause text is on the
    predicted page, or the quotes substantially overlap."""
    if pred.pdf_page == exp["source_page"]:
        return True
    page = doc.page(pred.pdf_page)
    if page is not None and verify_quote(exp["clause_text"], page.text):
        return True
    return overlap(pred.evidence_quote, exp["clause_text"]) >= 0.5


def value_ok(pred: ContractConstraint, exp: dict) -> bool | None:
    if exp["value"] is None:
        return None
    return pred.value is not None and abs(float(pred.value) - float(exp["value"])) < 1e-6


def match(expected: list[dict], preds: list[ContractConstraint], doc: ParsedDocument) -> list[dict]:
    rows = []
    for exp in expected:
        cands = [p for p in preds if p.constraint_type.value in TYPE_MAP[exp["constraint_type"]]
                 and location_ok(p, exp, doc)]
        cands.sort(key=lambda p: (value_ok(p, exp) is not True, p.pdf_page != exp["source_page"]))
        best = cands[0] if cands else None
        at_clause_other_type = [p.constraint_type.value for p in preds if best is None and location_ok(p, exp, doc)]
        row: dict[str, Any] = {"rule_id": exp["rule_id"], "document_id": exp["document_id"],
                               "reference_type": exp["constraint_type"], "detected": best is not None,
                               "types_at_clause_if_missed": sorted(set(at_clause_other_type))}
        if best is not None:
            row.update({
                "predicted_type": best.constraint_type.value, "predicted_page": best.pdf_page,
                "reference_page": exp["source_page"], "predicted_value": best.value,
                "reference_value": exp["value"], "value_correct": value_ok(best, exp),
                "unit_correct": (None if exp["unit"] is None else
                                 unit_family(best.unit) == unit_family(exp["unit"])),
                "value_kind_correct": (best.value_kind.value if best.value_kind else None) == exp["value_kind"],
                "conditions_presence_agrees": bool(best.conditions) == bool(exp["conditions"]),
                "exceptions_presence_agrees": bool(best.exceptions) == bool(exp["exceptions"]),
                "discretion_presence_agrees": bool(best.discretion) == bool(exp["discretion"]),
                "citation_correct": bool(best.quote_verified),
                "validation_issue_codes": [i["code"] for i in best.validation_issues],
            })
        rows.append(row)
    return rows


def rate(rows: list[dict], key: str) -> dict[str, Any]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return {"correct": sum(1 for v in vals if v), "n": len(vals),
            "rate": round(sum(1 for v in vals if v) / len(vals), 3) if vals else None}


def summarise(rows: list[dict], preds_by_doc: dict[str, list[ContractConstraint]],
              matched_ids: dict[str, set[str]]) -> dict[str, Any]:
    det = [r for r in rows if r["detected"]]
    all_preds = [p for ps in preds_by_doc.values() for p in ps]
    return {
        "reference_rules": len(rows),
        "detected_with_correct_type": {"correct": len(det), "n": len(rows),
                                       "rate": round(len(det) / len(rows), 3) if rows else None},
        "of_detected": {k: rate(det, k) for k in (
            "value_correct", "unit_correct", "value_kind_correct", "conditions_presence_agrees",
            "exceptions_presence_agrees", "discretion_presence_agrees", "citation_correct")},
        "predictions": len(all_preds),
        "unsupported_predictions_quote_not_on_cited_page": sum(1 for p in all_preds if not p.quote_verified),
        "predictions_with_value_not_in_quote": sum(
            1 for p in all_preds if any(i["code"] == "value_not_in_quote" for i in p.validation_issues)),
        "unmatched_predictions": sum(1 for d, ps in preds_by_doc.items()
                                     for p in ps if p.constraint_id not in matched_ids[d]),
    }


def retrieval_recall(docs: dict[str, ParsedDocument], expected: dict[str, list[dict]],
                     top_k_values=(8, 16, 32)) -> dict[str, Any]:
    """Share of reference clauses contained in the excerpts the LLM path would receive (its ceiling).
    Deterministic; no model calls."""
    out: dict[str, Any] = {}
    for k in top_k_values:
        hits: dict[str, list[str]] = {}
        for did, doc in docs.items():
            ex = retrieve_excerpts(doc, top_k=k)
            hits[did] = [e["rule_id"] for e in expected[did]
                         if any(verify_quote(e["clause_text"], x.text) or overlap(e["clause_text"], x.text) >= 0.8
                                for x in ex)]
        n = sum(len(v) for v in expected.values())
        h = sum(len(v) for v in hits.values())
        held_n = sum(len(v) for d, v in expected.items() if d not in DEVELOPMENT_DOCS)
        held_h = sum(len(v) for d, v in hits.items() if d not in DEVELOPMENT_DOCS)
        out[f"top_{k}"] = {"recall": f"{h}/{n}", "held_out_recall": f"{held_h}/{held_n}",
                           "per_document": {d: f"{len(hits[d])}/{len(expected[d])}" for d in docs}}
    return out


def build_llm_call():
    provider = os.environ.get("EVAL_LLM_PROVIDER", "").strip().lower()
    if provider not in ("anthropic", "openai"):
        return None, "not run: EVAL_LLM_PROVIDER not set to anthropic|openai"
    from app.config import get_settings
    from app.llm import DEFAULT_MODELS, build_provider
    key = os.environ.get("ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", "")
    model = os.environ.get("EVAL_LLM_MODEL") or DEFAULT_MODELS[provider]
    if not key:
        return None, f"not run: no API key in the environment for {provider}"
    if not model:
        return None, f"not run: EVAL_LLM_MODEL is required for {provider}"
    return build_provider(provider, key, model, get_settings()), None


def run_extractor(name: str, docs: dict[str, ParsedDocument], expected: dict[str, list[dict]],
                  llm=None) -> dict[str, Any]:
    rows: list[dict] = []
    preds_by_doc: dict[str, list[ContractConstraint]] = {}
    matched: dict[str, set[str]] = defaultdict(set)
    per_doc: dict[str, Any] = {}
    for did, doc in docs.items():
        t0 = time.perf_counter()
        usage = {"input_tokens": 0, "output_tokens": 0}
        error = None
        if llm is None:
            report = extract_rule_based(doc)
        else:
            def call(system: str, user: str, schema: dict, usage: dict = usage) -> dict:
                out = llm.extract_json(system, user, schema)
                if llm.last_usage:
                    usage["input_tokens"] += llm.last_usage.input_tokens
                    usage["output_tokens"] += llm.last_usage.output_tokens
                return out
            try:
                report = extract_with_llm(doc, call=call)
            except Exception as exc:  # noqa: BLE001 - recorded as a schema/provider failure
                report, error = None, f"{type(exc).__name__}: {getattr(exc, 'code', '') or 'failed'}"
        latency = time.perf_counter() - t0
        preds = report.constraints if report else []
        preds_by_doc[did] = preds
        drows = match(expected[did], preds, doc)
        for r in drows:
            if r["detected"]:
                pid = next((p.constraint_id for p in preds if p.constraint_type.value == r["predicted_type"]
                            and p.pdf_page == r["predicted_page"]), None)
                if pid:
                    matched[did].add(pid)
        rows += drows
        per_doc[did] = {"held_out": did not in DEVELOPMENT_DOCS, "latency_s": round(latency, 2),
                        "predictions": len(preds), "schema_valid_output": error is None,
                        "error": error, "tokens": usage if llm else None,
                        "detected": sum(r["detected"] for r in drows), "reference_rules": len(drows)}
    held = [r for r in rows if r["document_id"] not in DEVELOPMENT_DOCS]
    held_docs = {d: p for d, p in preds_by_doc.items() if d not in DEVELOPMENT_DOCS}
    return {
        "extractor": name,
        "overall": summarise(rows, preds_by_doc, matched),
        "held_out_only": summarise(held, held_docs, matched),
        "schema_valid_rate": round(sum(d["schema_valid_output"] for d in per_doc.values()) / len(per_doc), 3),
        "latency_s_total": round(sum(d["latency_s"] for d in per_doc.values()), 2),
        "cost": ("0 (no model calls)" if llm is None else
                 "not computed: token counts reported; provider prices are not hard-coded"),
        "per_document": per_doc,
        "per_rule": rows,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = ["# Extraction evaluation", "",
             f"Generated {report['generated_at']} by `scripts/evaluate_extraction.py` "
             f"(git {report['git_commit']}{' + uncommitted changes' if report['git_dirty'] else ''}).", "",
             "**Reference labels** are the source-checked rules in `data/evaluation/expected_rules.jsonl` "
             "(manually read against the cited page; pending human sign-off). They are not model output. "
             f"{report['reference_rules']} rules across {len(report['documents'])} real public documents; "
             "the set is small and not exhaustive, so treat rates as indicative only.", "",
             "Rule-based patterns were written against `contract_breit_001`; the *held-out* rows exclude it.", ""]
    for res in report["results"]:
        lines += [f"## {res['extractor']}", ""]
        if res.get("status"):
            lines += [f"Status: {res['status']}", ""]
            continue
        lines += ["| Metric | All documents | Held-out only |", "|---|---|---|"]
        o, h = res["overall"], res["held_out_only"]

        def fmt(x: dict) -> str:
            return "n/a" if x["rate"] is None else f"{x['correct']}/{x['n']} ({x['rate']:.0%})"
        lines.append(f"| Detected with correct type | {fmt(o['detected_with_correct_type'])} | "
                     f"{fmt(h['detected_with_correct_type'])} |")
        for k, label in (("value_correct", "Value correct (numeric rules)"), ("unit_correct", "Unit correct"),
                         ("value_kind_correct", "Value kind (max/min/exact/...)"),
                         ("conditions_presence_agrees", "Conditions present iff reference has them"),
                         ("exceptions_presence_agrees", "Exceptions present iff reference has them"),
                         ("discretion_presence_agrees", "Discretion present iff reference has it"),
                         ("citation_correct", "Citation: quote verbatim on cited page")):
            lines.append(f"| {label} (of detected) | {fmt(o['of_detected'][k])} | {fmt(h['of_detected'][k])} |")
        for k, label in (("predictions", "Predictions"),
                         ("unsupported_predictions_quote_not_on_cited_page", "Unsupported (quote not on page)"),
                         ("predictions_with_value_not_in_quote", "Value not in quote"),
                         ("unmatched_predictions", "Unmatched predictions (no reference rule)")):
            lines.append(f"| {label} | {o[k]} | {h[k]} |")
        lines += ["", f"Schema-valid output rate: {res['schema_valid_rate']:.0%}. "
                      f"Total latency: {res['latency_s_total']} s (includes no parsing). Cost: {res['cost']}.", "",
                  "| Document | Held-out | Detected | Predictions | Latency (s) |", "|---|---|---|---|---|"]
        for d, v in res["per_document"].items():
            lines.append(f"| {d} | {'yes' if v['held_out'] else 'no'} | {v['detected']}/{v['reference_rules']} | "
                         f"{v['predictions']} | {v['latency_s']} |")
        missed = [r for r in res["per_rule"] if not r["detected"]]
        if missed:
            lines += ["", "Missed reference rules:", ""]
            for r in missed:
                other = ", ".join(r["types_at_clause_if_missed"])
                lines.append(f"- `{r['rule_id']}`" + (f" (found other types at the clause: {other})" if other else ""))
        lines.append("")
    lines += ["## Retrieval recall (LLM path ceiling)", "",
              "Share of reference clauses contained in the retrieved excerpts sent to the model (deployed default "
              "`LLM_MAX_EXCERPTS=8`; about 2,000 characters each). An LLM cannot extract a clause it is not shown. "
              "No model calls. Caveat: the retrieval vocabulary (`SEARCH_TERMS`) was extended for these contract "
              "families while this dataset existed, so retrieval is not strictly held-out either.", "",
              "| top_k | All | Held-out | " + " | ".join(report["documents"]) + " |",
              "|---|---|---|" + "---|" * len(report["documents"])]
    for k, v in report["retrieval_recall"].items():
        lines.append(f"| {k.removeprefix('top_')} | {v['recall']} | {v['held_out_recall']} | "
                     + " | ".join(v["per_document"][d] for d in report["documents"]) + " |")
    lines += ["", "## Metric definitions", "",
              "- *Detected*: a prediction of an engine type mapped to the reference type (`TYPE_MAP`) that points "
              "at the reference clause (same page, the reference clause text is on the predicted page, or >=50% "
              "token overlap with the predicted quote).",
              "- *Conditions/exceptions/discretion*: presence agreement only; wording is not compared.",
              "- *Citation correct*: the predicted evidence quote appears verbatim (whitespace/hyphenation "
              "normalised) on the predicted PDF page.",
              "- *Unsupported*: predictions whose quote is not on the cited page, over all predictions.",
              "- *Unmatched*: predictions with no reference rule; the reference set is not exhaustive, so these "
              "are not necessarily wrong.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/evaluation"))
    args = ap.parse_args()

    expected: dict[str, list[dict]] = defaultdict(list)
    for line in EXPECTED.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            expected[r["document_id"]].append(r)
    paths = {row["document_id"]: ROOT / row["relative_path"] for row in csv.DictReader(MANIFEST.open())
             if row["document_id"] in expected}
    docs, parse_s, hashes = {}, {}, {}
    for did, path in paths.items():
        t0 = time.perf_counter()
        doc = parse_pdf(path)
        doc.document_id = did
        docs[did] = doc
        parse_s[did] = round(time.perf_counter() - t0, 2)
        hashes[did] = sha256(path)

    results = [run_extractor("rule_based", docs, expected)]
    retrieval = retrieval_recall(docs, expected)
    llm, why = build_llm_call()
    if llm is None:
        results.append({"extractor": "llm", "status": why})
    else:
        results.append(run_extractor(f"llm:{os.environ['EVAL_LLM_PROVIDER']}:{llm.model}", docs, expected, llm))

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=False).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                                text=True, check=False).stdout.strip())
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_commit": commit, "git_dirty": dirty,
        "python": platform.python_version(), "reference_file": str(EXPECTED.relative_to(ROOT)),
        "reference_sha256": sha256(EXPECTED), "reference_rules": sum(len(v) for v in expected.values()),
        "label_status": "source_checked during dataset preparation; pending human sign-off; not LLM output",
        "documents": {d: {"sha256": hashes[d], "pages": docs[d].page_count, "parse_s": parse_s[d],
                          "held_out_for_rule_based": d not in DEVELOPMENT_DOCS} for d in docs},
        "type_map": {k: sorted(v) for k, v in TYPE_MAP.items()},
        "retrieval_recall": retrieval,
        "results": results,
    }
    out = Path(args.out)
    (out / "extraction_eval_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (out / "extraction_eval_report.md").write_text(markdown(report))
    print(markdown(report))


if __name__ == "__main__":
    main()
