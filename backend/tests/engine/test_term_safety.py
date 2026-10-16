"""Engine-level safety: only approved terms affect results, and conflicting approved terms never silently win."""
import pytest

from app.engine.demo_data import DEMO_DIR
from app.engine.schemas import (
    AssetKey,
    Confidence,
    ConstraintType,
    ContractConstraint,
    ReviewStatus,
    SourceType,
)
from app.engine.simulator import (
    ContractTerms,
    Scenario,
    TermConflictError,
    simulate_contract_aware,
    terms_from_constraints,
)

REIT_CAP = (ConstraintType.REDEMPTION_MONTHLY_CAP, AssetKey.NON_TRADED_REIT)
SBL_ADV = (ConstraintType.SBL_ADVANCE_RATE, AssetKey.SBL)


def term(kind, value, status, cid="c1", doc="doc.pdf", page=1):
    ctype, asset = kind
    return ContractConstraint(constraint_id=cid, constraint_type=ctype, asset_key=asset, description="t", value=value,
                              unit="%", document_id=doc, document_name=doc, pdf_page=page, evidence_quote="q",
                              quote_verified=True, interpretation="i", confidence=Confidence.HIGH,
                              source_type=SourceType.SOURCE_BACKED, review_status=status)


@pytest.mark.parametrize("status", [ReviewStatus.NEEDS_REVIEW, ReviewStatus.REJECTED])
def test_unapproved_terms_cannot_affect_direct_engine_calls(status):
    t = terms_from_constraints([term(REIT_CAP, 9, status), term(SBL_ADV, 90, status, cid="c2")])
    default = ContractTerms()
    assert t.reit_monthly_cap_pct == default.reit_monthly_cap_pct
    assert t.sbl_advance_rate == default.sbl_advance_rate
    assert t.provenance["reit_monthly_cap_pct"].startswith("default")
    assert t.excluded_unapproved == ["c1", "c2"]
    s = Scenario()
    assert simulate_contract_aware(s, t).peak_shortfall == simulate_contract_aware(s, ContractTerms()).peak_shortfall


def test_unknown_status_fails_closed():
    c = term(REIT_CAP, 9, ReviewStatus.CONFIRMED)
    c = c.model_copy(update={"review_status": "approved_by_llm"})  # bypasses enum validation
    t = terms_from_constraints([c])
    assert t.reit_monthly_cap_pct == 2.0 and t.excluded_unapproved == ["c1"]


def test_qualitative_unapproved_term_does_not_count_as_source():
    pro_rata = term((ConstraintType.PRO_RATA_FULFILLMENT, AssetKey.NON_TRADED_REIT), None, ReviewStatus.NEEDS_REVIEW)
    assert terms_from_constraints([pro_rata]).provenance["reit_pro_rata"].startswith("default")


@pytest.mark.parametrize("order", [0, 1])
def test_conflicting_approved_terms_raise_regardless_of_order(order):
    a = term(REIT_CAP, 2, ReviewStatus.CONFIRMED, cid="new", doc="supplement_2026.pdf", page=53)
    b = term(REIT_CAP, 5, ReviewStatus.EDITED, cid="old", doc="prospectus_2019.pdf", page=12)
    with pytest.raises(TermConflictError) as e:
        terms_from_constraints([a, b] if order == 0 else [b, a])
    (conflict,) = e.value.conflicts
    assert conflict["term"] == "reit_monthly_cap_pct"
    assert {(x["constraint_id"], x["value"], x["document"], x["pdf_page"]) for x in conflict["candidates"]} == {
        ("new", 2.0, "supplement_2026.pdf", 53), ("old", 5.0, "prospectus_2019.pdf", 12)}
    assert "supplement_2026.pdf p.53" in str(e.value) and "prospectus_2019.pdf p.12" in str(e.value)


def test_all_conflicts_reported_together():
    with pytest.raises(TermConflictError) as e:
        terms_from_constraints([term(REIT_CAP, 2, ReviewStatus.CONFIRMED, cid="a"),
                                term(REIT_CAP, 3, ReviewStatus.CONFIRMED, cid="b"),
                                term(SBL_ADV, 50, ReviewStatus.CONFIRMED, cid="c"),
                                term(SBL_ADV, 70, ReviewStatus.CONFIRMED, cid="d")])
    assert {c["term"] for c in e.value.conflicts} == {"reit_monthly_cap_pct", "sbl_advance_rate"}


def test_unreviewed_term_cannot_create_a_conflict():
    t = terms_from_constraints([term(REIT_CAP, 2, ReviewStatus.CONFIRMED, cid="ok"),
                                term(REIT_CAP, 5, ReviewStatus.NEEDS_REVIEW, cid="pending")])
    assert t.reit_monthly_cap_pct == 2.0 and t.excluded_unapproved == ["pending"]


def test_agreeing_approved_terms_corroborate():
    t = terms_from_constraints([term(REIT_CAP, 2, ReviewStatus.CONFIRMED, cid="a", doc="prospectus.pdf", page=53),
                                term(REIT_CAP, 2.0, ReviewStatus.EDITED, cid="b", doc="supplement.pdf", page=7)])
    assert t.reit_monthly_cap_pct == 2.0
    assert "prospectus.pdf p.53" in t.provenance["reit_monthly_cap_pct"]
    assert "supplement.pdf p.7" in t.provenance["reit_monthly_cap_pct"]


def test_non_conflicting_approved_terms_still_apply():
    t = terms_from_constraints([term(REIT_CAP, 1.5, ReviewStatus.CONFIRMED, cid="a"),
                                term(SBL_ADV, 40, ReviewStatus.EDITED, cid="b"),
                                term((ConstraintType.PRO_RATA_FULFILLMENT, AssetKey.NON_TRADED_REIT), None,
                                     ReviewStatus.CONFIRMED, cid="c", page=4)])
    assert t.reit_monthly_cap_pct == 1.5 and t.sbl_advance_rate == pytest.approx(0.40)
    assert t.reit_pro_rata is True and "doc.pdf p.4 (confirmed)" in t.provenance["reit_pro_rata"]
    assert t.excluded_unapproved == []


def test_demo_contracts_all_approved_produce_the_same_terms_as_before():
    """Regression: the synthetic demo contracts (one clause per input) are unaffected by the stricter rules."""
    from app.engine.constraint_extractor import extract_rule_based
    from app.engine.document_parser import parse_pdf
    from app.engine.synthetic_docs import ensure_synthetic_docs
    cons = [c for p in ensure_synthetic_docs(DEMO_DIR) for c in extract_rule_based(parse_pdf(p)).constraints]
    for c in cons:
        c.review_status = ReviewStatus.CONFIRMED
    t = terms_from_constraints(cons)
    assert t.excluded_unapproved == []
    assert (t.interval_offer_pct, t.interval_fee_pct, t.sbl_advance_rate, t.sbl_maintenance_ltv,
            t.rsu_withholding_rate) == (5.0, 2.0, 0.5, 0.6, 0.22)
