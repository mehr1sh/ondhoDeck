import pytest

from app.engine.constraint_extractor import QUALITATIVE_TYPES, extract_rule_based, extract_with_llm, verify_quote
from app.engine.demo_data import BREIT_PDF, DEMO_DIR
from app.engine.document_parser import parse_pdf
from app.engine.llm_service import LLMError
from app.engine.schemas import ConstraintType, ReviewStatus, SourceType
from app.engine.simulator import terms_from_constraints
from app.engine.synthetic_docs import ensure_synthetic_docs

breit_required = pytest.mark.skipif(not BREIT_PDF.exists(), reason="BREIT prospectus PDF not present")


@pytest.fixture(scope="module")
def breit():
    doc = parse_pdf(BREIT_PDF)
    return doc, extract_rule_based(doc)


@breit_required
def test_breit_caps_extracted_from_real_text_with_pages(breit):
    doc, report = breit
    by_type = {c.constraint_type: c for c in report.constraints}
    monthly = by_type[ConstraintType.REDEMPTION_MONTHLY_CAP]
    quarterly = by_type[ConstraintType.REDEMPTION_QUARTERLY_CAP]
    assert monthly.value == 2.0 and quarterly.value == 5.0
    for c in (monthly, quarterly):
        assert c.source_type == SourceType.SOURCE_BACKED
        assert c.quote_verified
        assert verify_quote(c.evidence_quote, doc.page(c.pdf_page).text)  # quote really is on that page
    assert "per month" in monthly.evidence_quote and "per calendar quarter" in quarterly.evidence_quote
    assert "assessed" in quarterly.evidence_quote  # both limits assessed each month


@breit_required
def test_qualitative_breit_rules_have_no_numeric_value(breit):
    _, report = breit
    types = {c.constraint_type: c for c in report.constraints}
    for t in (ConstraintType.BOARD_DISCRETION, ConstraintType.PRO_RATA_FULFILLMENT, ConstraintType.RESUBMISSION_REQUIRED):
        c = types[t]
        assert c.value is None and c.lower_bound is None and c.upper_bound is None
        assert c.is_qualitative
    assert "none at all" in types[ConstraintType.BOARD_DISCRETION].evidence_quote


def test_evidence_and_pages_stay_attached_through_review_and_terms():
    paths = ensure_synthetic_docs(DEMO_DIR)
    cons = [c for p in paths for c in extract_rule_based(parse_pdf(p)).constraints]
    assert cons and all(c.source_type == SourceType.SYNTHETIC_DOCUMENT for c in cons)
    for c in cons:
        assert c.evidence_quote and c.pdf_page >= 1 and c.quote_verified
    adv = next(c for c in cons if c.constraint_type == ConstraintType.SBL_ADVANCE_RATE)
    before = (adv.evidence_quote, adv.pdf_page, adv.document_name)
    adv.value = 45.0
    adv.review_status = ReviewStatus.EDITED
    terms = terms_from_constraints(cons)
    assert terms.sbl_advance_rate == pytest.approx(0.45)
    assert (adv.evidence_quote, adv.pdf_page, adv.document_name) == before
    assert adv.original_value == 50.0
    assert f"p.{adv.pdf_page}" in terms.provenance["sbl_advance_rate"]


def test_rejected_constraint_falls_back_to_labelled_default():
    paths = ensure_synthetic_docs(DEMO_DIR)
    cons = [c for p in paths for c in extract_rule_based(parse_pdf(p)).constraints]
    for c in cons:
        if c.constraint_type == ConstraintType.SBL_MAINTENANCE_THRESHOLD:
            c.review_status = ReviewStatus.REJECTED
    terms = terms_from_constraints(cons)
    assert "default" in terms.provenance["sbl_maintenance_ltv"]


def test_llm_output_strips_numbers_from_qualitative_clauses(monkeypatch):
    doc = parse_pdf(ensure_synthetic_docs(DEMO_DIR)[0])  # interval fund policy
    page = doc.pages[0]
    quote = "the Fund will repurchase tendered Shares on a pro rata basis."
    fake = {"terms": [
        {"excerpt_id": "unknown", "constraint_type": "pro_rata_fulfillment", "asset_key": "interval_fund",
         "description": "pro rata", "value": 35.0, "lower_bound": None, "upper_bound": None, "unit": "%",
         "timing": None, "conditions": None, "evidence_quote": quote, "interpretation": "x",
         "confidence": "high", "ambiguous": False},
        {"excerpt_id": "unknown", "constraint_type": "repurchase_fee", "asset_key": "interval_fund",
         "description": "fee", "value": 2.0, "lower_bound": None, "upper_bound": None, "unit": "%",
         "timing": None, "conditions": None, "evidence_quote": "This sentence is not in the document.",
         "interpretation": "x", "confidence": "high", "ambiguous": False},
    ]}
    monkeypatch.setattr("app.engine.constraint_extractor.call_structured", lambda *a, **k: fake)
    report = extract_with_llm(doc)
    pr, fee = report.constraints
    assert pr.constraint_type in QUALITATIVE_TYPES and pr.value is None
    assert pr.quote_verified and pr.pdf_page == page.pdf_page
    assert not fee.quote_verified and fee.confidence.value == "low"
    assert all(c.review_status == ReviewStatus.NEEDS_REVIEW for c in report.constraints)


def test_llm_malformed_output_retries_once_then_fails(monkeypatch):
    doc = parse_pdf(ensure_synthetic_docs(DEMO_DIR)[1])
    calls = []

    def bad(*a, **k):
        calls.append(1)
        return {"terms": [{"nonsense": True}]}

    monkeypatch.setattr("app.engine.constraint_extractor.call_structured", bad)
    with pytest.raises(LLMError):
        extract_with_llm(doc)
    assert len(calls) == 2


def test_missing_api_key_raises_informative_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.engine.llm_service import call_structured
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        call_structured("s", "u", {"type": "object"})


def test_demo_falls_back_to_snapshot_when_breit_pdf_missing(monkeypatch, tmp_path):
    import app.engine.demo_data as dd
    monkeypatch.setattr(dd, "BREIT_PDF", tmp_path / "missing.pdf")
    docs, reports, msgs = dd.load_demo_documents()
    assert any("snapshot" in m for m in msgs)
    breit = reports[0]
    caps = [c for c in breit.constraints if c.constraint_type == ConstraintType.REDEMPTION_MONTHLY_CAP]
    assert caps and caps[0].value == 2.0 and caps[0].evidence_quote and caps[0].pdf_page >= 1
