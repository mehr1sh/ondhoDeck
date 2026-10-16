"""Evidence validation, duplicate handling and simulator-safety regressions (mocked model output; no network)."""
from dataclasses import fields

import pytest

from app.engine.constraint_extractor import extract_from_excerpts
from app.engine.contract_validation import dedupe_constraints, validate_constraints
from app.engine.document_parser import PageText, ParsedDocument
from app.engine.retrieval import Excerpt
from app.engine.schemas import (
    AssetKey,
    Confidence,
    ConstraintType,
    ContractConstraint,
    ReviewStatus,
    SourceType,
    ValueKind,
)
from app.engine.simulator import (
    ContractTerms,
    Scenario,
    TermConflictError,
    pro_rata_fill,
    settlement_lag_months,
    simulate_contract_aware,
    terms_from_constraints,
)
from app.services.engine_adapter import term_rows, terms_snapshot
from app.services.explanation import build_explanation

T, A = ConstraintType, AssetKey
CAP_QUOTE = "repurchases are limited to no more than 2% of aggregate NAV per month"
SETTLE_QUOTE = "Settlements of share repurchases will be made within three business days of the Repurchase Date."
RESUB_248 = ("If the transaction price is not made available by the tenth business day, then no repurchase requests "
             "will be accepted for such month and stockholders must resubmit their repurchase requests.")
RESUB_270 = ("All unsatisfied repurchase requests must be resubmitted after the start of the next month or quarter, "
             "or upon the recommencement of our share repurchase plan, as applicable.")


def doc_with(pages: dict[int, str]) -> ParsedDocument:
    return ParsedDocument("d", "prospectus.pdf", pages=[PageText(n, t) for n, t in pages.items()])


def model_term(excerpt_id, ctype, quote, value=None, unit=None, kind="qualitative", ambiguous=False):
    return {"excerpt_id": excerpt_id, "constraint_type": ctype, "asset_key": "non_traded_reit", "description": "x",
            "value": value, "lower_bound": None, "upper_bound": None, "unit": unit, "timing": None,
            "conditions": None, "exceptions": [], "discretion": None, "value_kind": kind, "evidence_quote": quote,
            "interpretation": "x", "confidence": "high", "ambiguous": ambiguous}


def run_model(doc, terms, cited_pages):
    excerpts = [Excerpt(f"p{n}-c0", "d", doc.name, n, None, doc.page(n).text, 10.0) for n in cited_pages]
    return extract_from_excerpts(doc, excerpts, lambda s, u, sch: {"terms": terms}).constraints


def term(ctype, value=None, status=ReviewStatus.CONFIRMED, quote=CAP_QUOTE, cid="c1", page=1, unit="%",
         verified=True, issues=None, kind=None, asset=A.NON_TRADED_REIT):
    return ContractConstraint(constraint_id=cid, constraint_type=ctype, asset_key=asset, description="t", value=value,
                              unit=unit, document_id="d", document_name="prospectus.pdf", pdf_page=page,
                              evidence_quote=quote, quote_verified=verified, interpretation="i",
                              confidence=Confidence.HIGH, source_type=SourceType.SOURCE_BACKED, review_status=status,
                              validation_issues=issues or [], value_kind=kind)


def codes(c):
    return [i["code"] for i in c.validation_issues]


# 1-2 page-specific evidence ----------------------------------------------------------------------------------

def test_quote_on_cited_page_passes():
    doc = doc_with({1: "Intro.", 2: f"Plan terms: {CAP_QUOTE}."})
    (c,) = run_model(doc, [model_term("p2-c0", "redemption_monthly_cap", CAP_QUOTE, 2, "% of NAV", "maximum")], [2])
    assert c.quote_verified and c.pdf_page == 2 and c.confidence == Confidence.HIGH
    assert not [i for i in c.validation_issues if i["severity"] == "error"]


def test_quote_found_only_on_another_page_is_flagged_not_moved():
    doc = doc_with({1: f"Summary: {CAP_QUOTE}.", 2: "Unrelated page about fees."})
    (c,) = run_model(doc, [model_term("p2-c0", "redemption_monthly_cap", CAP_QUOTE, 2, "% of NAV", "maximum")], [2])
    assert c.pdf_page == 2 and not c.quote_verified and c.confidence == Confidence.LOW  # citation kept as given
    issue = c.validation_issues[0]
    assert issue["code"] == "quote_not_on_cited_page" and issue["severity"] == "error"
    assert "PDF page(s) 1" in issue["message"]


# 3 numeric support --------------------------------------------------------------------------------------------

def test_value_not_in_quote_is_an_error_and_cannot_drive_simulation_as_extracted():
    c = term(T.REDEMPTION_MONTHLY_CAP, 3, quote=CAP_QUOTE)  # quote says 2%
    validate_constraints([c])
    assert "value_not_in_quote" in codes(c) and c.confidence == Confidence.LOW
    t = terms_from_constraints([c])
    assert t.reit_monthly_cap_pct == ContractTerms().reit_monthly_cap_pct  # default, not 3
    assert t.excluded_unsupported[0]["reasons"] == ["value_not_in_quote"]


def test_reviewer_edited_value_is_used_but_unverified_citation_never_is():
    edited = term(T.REDEMPTION_MONTHLY_CAP, 1.5, status=ReviewStatus.EDITED,
                  issues=[{"code": "value_not_in_quote", "severity": "error", "message": "m"}])
    assert terms_from_constraints([edited]).reit_monthly_cap_pct == 1.5
    bad_cite = term(T.REDEMPTION_MONTHLY_CAP, 2, status=ReviewStatus.EDITED, verified=False)
    t = terms_from_constraints([bad_cite])
    assert t.reit_monthly_cap_pct == ContractTerms().reit_monthly_cap_pct
    assert t.excluded_unsupported[0]["reasons"] == ["quote_not_verified_on_cited_page"]


# 4 ambiguity ------------------------------------------------------------------------------------------------

def test_ambiguous_interpretation_stays_in_review():
    doc = doc_with({1: "The board may repurchase fewer shares than requested, or none at all, in its discretion."})
    (c,) = run_model(doc, [model_term("p1-c0", "board_discretion",
                                      "The board may repurchase fewer shares than requested, or none at all, in its "
                                      "discretion.", ambiguous=True)], [1])
    assert c.ambiguous and c.review_status == ReviewStatus.NEEDS_REVIEW and c.value is None
    assert terms_from_constraints([c]).excluded_unapproved == [c.constraint_id]


# 5 caps are limits, not payouts ------------------------------------------------------------------------------

def test_redemption_cap_is_a_fund_level_limit_not_a_guaranteed_payout():
    assert pro_rata_fill(demand_pct=10, capacity_pct=2) == pytest.approx(0.2)
    c = term(T.REDEMPTION_QUARTERLY_CAP, 5, quote="no more than 5% of aggregate NAV per calendar quarter",
             kind=ValueKind.EXACT)
    validate_constraints([c])
    assert "cap_not_maximum" in codes(c)
    s = Scenario(reit_board_fill_factor=0.0)  # board fills nothing: caps permit, they do not guarantee
    rows = simulate_contract_aware(s, ContractTerms()).rows
    assert sum(r["reit_proceeds"] for r in rows) == 0 and any(r["reit_requested"] > 0 for r in rows)
    s2 = Scenario(reit_base_demand_pct=10.0, reit_demand_sensitivity=0.0)
    binding = " ".join(b for r in simulate_contract_aware(s2, ContractTerms()).rows for b in r["binding_constraints"])
    assert "fund-level cap" in binding and "monthly 2%" in binding


def test_cap_text_reports_the_approved_values():
    c = term(T.REDEMPTION_MONTHLY_CAP, 1, quote="limited to no more than 1% of aggregate NAV per month")
    s = Scenario(reit_base_demand_pct=10.0, reit_demand_sensitivity=0.0)
    binding = " ".join(b for r in simulate_contract_aware(s, terms_from_constraints([c])).rows
                       for b in r["binding_constraints"])
    assert "monthly 1%" in binding and "monthly 2%" not in binding


# 6 settlement timing -----------------------------------------------------------------------------------------

def test_settlement_within_three_business_days_is_a_maximum_and_only_a_derived_lag():
    ok = term(T.SETTLEMENT_TIMING, 3, quote=SETTLE_QUOTE, unit="business days", kind=ValueKind.MAXIMUM)
    exact = term(T.SETTLEMENT_TIMING, 3, quote=SETTLE_QUOTE, unit="business days", kind=ValueKind.EXACT, cid="c2")
    validate_constraints([ok])
    validate_constraints([exact])
    assert "value_kind_conflicts_with_quote" not in codes(ok)
    assert "value_kind_conflicts_with_quote" in codes(exact) and exact.ambiguous
    assert settlement_lag_months(ok) == 1
    assert settlement_lag_months(term(T.SETTLEMENT_TIMING, 45, unit="business days")) == 3
    t = terms_from_constraints([ok])
    assert t.reit_settlement_lag_months == 1 and "reit_settlement_lag_months" in t.derived
    row = next(r for r in term_rows(terms_snapshot(t)) if r["term"] == "reit_settlement_lag_months")
    assert row["basis"] == "derived_from_clause" and row["source_backed"] is False
    assert "not a guaranteed date" in row["provenance"]


# 7 overlapping resubmission clauses --------------------------------------------------------------------------

def test_distinct_resubmission_rules_are_kept_and_cross_referenced():
    a = term(T.RESUBMISSION_REQUIRED, quote=RESUB_248, page=248, cid="a", unit=None)
    b = term(T.RESUBMISSION_REQUIRED, quote=RESUB_270, page=270, cid="b", unit=None)
    kept = dedupe_constraints([a, b])
    validate_constraints(kept)
    assert [c.constraint_id for c in kept] == ["a", "b"]
    rel_a = next(i for i in a.validation_issues if i["code"] == "related_clause")
    rel_b = next(i for i in b.validation_issues if i["code"] == "related_clause")
    assert "PDF page 270" in rel_a["message"] and "PDF page 248" in rel_b["message"] and rel_a["severity"] == "info"


def test_exact_repeat_is_merged_with_its_page_kept():
    a = term(T.RESUBMISSION_REQUIRED, quote=RESUB_270, page=270, cid="a", unit=None)
    repeat = term(T.RESUBMISSION_REQUIRED, quote="  " + RESUB_270, page=42, cid="b", unit=None)
    kept = dedupe_constraints([a, repeat])
    assert [c.constraint_id for c in kept] == ["a"] and kept[0].corroborating_pages == [42]


def test_same_type_different_values_flag_a_conflict():
    m1 = term(T.REDEMPTION_MONTHLY_CAP, 2, cid="m1", page=53)
    m2 = term(T.REDEMPTION_MONTHLY_CAP, 1, quote="no more than 1% of aggregate NAV per month", cid="m2", page=300)
    validate_constraints([m1, m2])
    assert "conflicting_values" in codes(m1) and "conflicting_values" in codes(m2)


# 11 conflicts are not resolved by insertion order --------------------------------------------------------------

def test_conflicting_settlement_periods_raise():
    with pytest.raises(TermConflictError):
        terms_from_constraints([term(T.SETTLEMENT_TIMING, 3, quote=SETTLE_QUOTE, unit="business days", cid="s1"),
                                term(T.SETTLEMENT_TIMING, 2, quote="within two months", unit="months", cid="s2")])


# 12 qualitative restrictions -----------------------------------------------------------------------------------

def test_qualitative_restrictions_have_no_numeric_effect():
    qual = [term(t, quote="The board may modify or suspend the plan.", cid=t.value, unit=None)
            for t in (T.BOARD_DISCRETION, T.REDEMPTION_SUSPENSION, T.RESUBMISSION_REQUIRED, T.REDEMPTION_NOTICE_PERIOD)]
    t, base = terms_from_constraints(qual), ContractTerms()
    numeric = [f.name for f in fields(ContractTerms) if f.name not in ("provenance", "excluded_unapproved",
                                                                       "excluded_unsupported", "applied", "derived")]
    assert all(getattr(t, f) == getattr(base, f) for f in numeric) and t.applied == {}


# 13 explanations cite what was applied ---------------------------------------------------------------------------

def test_explanation_cites_only_applied_rules_and_lists_unmodelled_ones():
    cap = term(T.REDEMPTION_MONTHLY_CAP, 1, quote="limited to no more than 1% of aggregate NAV per month", cid="cap")
    board = term(T.BOARD_DISCRETION, quote="The board may repurchase fewer shares or none.", cid="board", unit=None)
    terms = terms_from_constraints([cap, board])
    s = Scenario(reit_base_demand_pct=10.0, reit_demand_sensitivity=0.0)
    evidence = [{"id": "cap", "revision": 2, "type": "redemption_monthly_cap", "asset_key": "non_traded_reit",
                 "document": "prospectus.pdf", "pdf_page": 1, "quote": cap.evidence_quote, "value": "1"},
                {"id": "board", "revision": 2, "type": "board_discretion", "asset_key": "non_traded_reit",
                 "document": "prospectus.pdf", "pdf_page": 1, "quote": board.evidence_quote, "value": None}]
    exp = build_explanation(s, terms, simulate_contract_aware(s, terms), evidence)
    assert exp["first_shortfall_month"] is not None
    reit = next(r for r in exp["contributing_rules"] if r["relaxation"] == "reit_gate")
    assert [e["id"] for e in reit["evidence"]] == ["cap"] and reit["evidence"][0]["role"] == "applied"
    assert [e["id"] for e in exp["not_modelled"]] == ["board"]
    assert "no numerical effect" in exp["not_modelled"][0]["reason"]
