"""Reproducible Demo Mode: synthetic household + constraints extracted deterministically.

Demo Mode never invents contract text. Constraints come from running the
rule-based extractor over (a) the supplied BREIT prospectus and (b) the
clearly-labelled synthetic sample contracts generated into data/demo/. If the
BREIT PDF is missing, a snapshot of a previous rule-based extraction of that
same PDF (data/demo/constraints_snapshot.json) is used and labelled as such.
"""
from __future__ import annotations

import json
from pathlib import Path

from .constraint_extractor import extract_rule_based
from .document_parser import ParsedDocument, parse_pdf
from .schemas import ContractConstraint, ExtractionReport
from .simulator import Scenario
from .synthetic_docs import ensure_synthetic_docs

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEMO_DIR = DATA_DIR / "demo"
BREIT_PDF = DATA_DIR / "BREIT-Prospectus-with-previous-supplements.pdf"
SNAPSHOT = DEMO_DIR / "constraints_snapshot.json"


def demo_scenario() -> Scenario:
    """The seeded demo household. Every number is synthetic; see SCENARIO_NOTES."""
    return Scenario()


# Provenance labels shown next to scenario inputs in the UI.
SCENARIO_NOTES: dict[str, str] = {
    "holdings": "Synthetic household from the SlipSlopes presentation ($1.80M paper assets).",
    "flows": "Synthetic monthly income/expenses.",
    "stress": "Scenario assumption: 2022-style equity drawdown path (linear to trough, hold, partial recovery).",
    "betas": "Scenario assumption: sensitivity of each asset's value to the equity drawdown.",
    "sbl": "Synthetic loan balance; advance rate / maintenance threshold come from the synthetic SBL agreement.",
    "capital_calls": "Scenario assumption: the synthetic LPA leaves call timing to GP discretion.",
    "rsu": ("Synthetic vest; withholding rate from the synthetic RSU grant; effective tax rate is an assumption. "
            "Household policy assumption: in open trading windows, vested RSUs are sold to keep 3 months of net "
            "spending in cash."),
    "redemptions": "Household plan: amounts requested from the REIT and interval fund (resubmitted until filled).",
    "demand": ("Scenario assumption: aggregate redemption demand from all investors as % of NAV. No supplied "
               "document discloses this; it determines the pro-rata fill rate."),
    "board": ("Scenario assumption: share of the 2%/5% cap the board actually honours. The prospectus says the "
              "board may repurchase fewer shares or none; 100% means the board fills up to the caps."),
}


def load_demo_documents() -> tuple[dict[str, ParsedDocument], list[ExtractionReport], list[str]]:
    """Parse + rule-extract BREIT and the synthetic contracts. Returns (docs, reports, messages)."""
    docs, reports, messages = {}, [], []
    if BREIT_PDF.exists():
        doc = parse_pdf(BREIT_PDF)
        if doc.errors and not doc.pages:
            messages.append(f"BREIT prospectus could not be parsed: {doc.errors[0]}")
        else:
            docs[doc.document_id] = doc
            reports.append(extract_rule_based(doc))
            if doc.failed_pages:
                messages.append(f"BREIT: {len(doc.failed_pages)} page(s) had no extractable text "
                                f"(e.g. {doc.failed_pages[:5]}); review those pages manually if relevant.")
    elif SNAPSHOT.exists():
        data = json.loads(SNAPSHOT.read_text())
        reports.append(ExtractionReport.model_validate(data))
        messages.append("BREIT PDF not found in data/; using the saved rule-based extraction snapshot.")
    else:
        messages.append("BREIT PDF not found and no snapshot available; REIT terms use labelled defaults.")
    for path in ensure_synthetic_docs(DEMO_DIR):
        doc = parse_pdf(path)
        docs[doc.document_id] = doc
        reports.append(extract_rule_based(doc))
    return docs, reports, messages


def all_constraints(reports: list[ExtractionReport]) -> list[ContractConstraint]:
    return [c for r in reports for c in r.constraints]


def write_snapshot() -> Path:
    """Regenerate the BREIT snapshot from the real PDF (run once; requires the PDF)."""
    report = extract_rule_based(parse_pdf(BREIT_PDF))
    SNAPSHOT.write_text(report.model_dump_json(indent=2))
    return SNAPSHOT
