"""Document upload validation, processing jobs, retries, evidence pages, downloads and deletion."""
import uuid
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import func, select

from app.models import Document, DocumentPage, ExtractedConstraint, ProcessingJob
from app.services import processing
from app.services.ocr import ocr_available

from .conftest import make_pdf, upload

FIXTURES = Path(__file__).resolve().parents[2] / "app" / "engine" / "fixtures"
SBL_PDF = (FIXTURES / "SYNTHETIC_Securities_Backed_Line_Agreement.pdf").read_bytes()


@pytest.fixture
def hid(alice):
    return alice.post("/households", json={"name": "Docs"}).json()["id"]


def _init(user, hid, data, filename="a.pdf", category="sbl_agreement"):
    return user.post(f"/households/{hid}/documents", json={"filename": filename, "category": category,
                                                            "size_bytes": len(data)})


def test_initiate_rejects_non_pdf_and_oversize(alice, hid, settings):
    assert _init(alice, hid, b"x", filename="notes.docx").json()["error"]["code"] == "unsupported_media_type"
    big = alice.post(f"/households/{hid}/documents", json={"filename": "a.pdf", "category": "other",
                                                            "size_bytes": settings.max_upload_mb * 1024 * 1024 + 1})
    assert big.status_code == 413


@pytest.mark.parametrize("content,status,code", [
    (b"", 422, "unprocessable"),
    (b"PK\x03\x04 this is a zip file", 415, "unsupported_media_type"),
    (b"%PDF-1.7\n garbage that is not a pdf body", 422, "unprocessable"),
])
def test_content_validation(alice, hid, content, status, code):
    doc = _init(alice, hid, content or b"x").json()["document"]
    r = alice.put(f"/documents/{doc['id']}/content", content=content, headers={"Content-Type": "application/pdf"})
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert alice.get(f"/documents/{doc['id']}").json()["status"] == "pending_upload"


def test_encrypted_pdf_rejected(alice, hid):
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "secret")
    data = d.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc = _init(alice, hid, data).json()["document"]
    r = alice.put(f"/documents/{doc['id']}/content", content=data, headers={"Content-Type": "application/pdf"})
    assert r.status_code == 422 and "Password" in r.json()["error"]["message"]


def test_wrong_content_type_rejected(alice, hid):
    doc = _init(alice, hid, SBL_PDF).json()["document"]
    r = alice.put(f"/documents/{doc['id']}/content", content=SBL_PDF, headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_full_pipeline_extracts_verified_constraints(alice, hid, db):
    doc, job = upload(alice, hid, SBL_PDF, filename="../../SYNTHETIC SBL agreement?.pdf")
    assert job["status"] in ("queued", "succeeded")
    doc = alice.get(f"/documents/{doc['id']}").json()
    assert doc["status"] == "extracted", doc
    assert doc["latest_job"]["status"] == "succeeded" and doc["latest_job"]["extraction_method"] == "rule_based"
    assert doc["page_count"] == 2 and doc["constraint_count"] == 4
    stored = db.get(Document, uuid.UUID(doc["id"]))
    assert "/" not in stored.safe_filename and ".." not in stored.storage_path
    cons = alice.get(f"/households/{hid}/constraints").json()
    by_type = {c["constraint_type"]: c for c in cons}
    adv = by_type["sbl_advance_rate"]
    assert float(adv["value"]) == 50.0 and adv["quote_verified"] and adv["review_status"] == "needs_review"
    assert adv["source_type"] == "synthetic_document"  # sample contract, not a real agreement
    page = alice.get(f"/documents/{doc['id']}/pages/{adv['pdf_page']}").json()
    assert " ".join(adv["evidence_quote"].split()) in " ".join(page["text"].split())
    assert alice.get(f"/documents/{doc['id']}/pages/99").status_code == 404


def test_complete_is_idempotent_and_duplicates_detected(alice, hid, db):
    doc, job = upload(alice, hid, SBL_PDF)
    again = alice.post(f"/documents/{doc['id']}/complete").json()
    assert again["id"] == job["id"]
    assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 1
    dup, _ = upload(alice, hid, SBL_PDF)
    assert dup["id"] == doc["id"]  # same bytes -> existing document, no second upload
    n = db.scalar(select(func.count()).select_from(ExtractedConstraint))
    assert n == 4


def test_complete_requires_content(alice, hid):
    doc = _init(alice, hid, SBL_PDF).json()["document"]
    assert alice.post(f"/documents/{doc['id']}/complete").status_code == 409


def test_failed_job_can_be_retried_without_duplicates(alice, hid, db, monkeypatch):
    real = processing.run_pipeline

    def boom(job_id, **kw):
        raise processing.JobFailure("extraction_failed", "Extraction failed: simulated provider rejection")

    monkeypatch.setattr(processing, "run_pipeline", boom)
    doc, job = upload(alice, hid, SBL_PDF)
    doc = alice.get(f"/documents/{doc['id']}").json()
    assert doc["status"] == "failed" and doc["error_code"] == "extraction_failed"
    assert doc["latest_job"]["status"] == "failed"
    # A retry while the failure persists creates a second job, which fails again.
    first_retry = alice.post(f"/documents/{doc['id']}/retry")
    assert first_retry.status_code == 202
    assert alice.get(f"/documents/{doc['id']}").json()["status"] == "failed"

    monkeypatch.setattr(processing, "run_pipeline", real)
    r = alice.post(f"/documents/{doc['id']}/retry", headers={"Idempotency-Key": "retry-1"})
    assert r.status_code == 202
    again = alice.post(f"/documents/{doc['id']}/retry", headers={"Idempotency-Key": "retry-1"})
    assert again.json()["id"] == r.json()["id"]  # same key -> same job
    doc = alice.get(f"/documents/{doc['id']}").json()
    assert doc["status"] == "extracted" and doc["constraint_count"] == 4
    jobs = alice.get(f"/documents/{doc['id']}/jobs").json()
    assert [j["status"] for j in jobs][0] == "succeeded" and len(jobs) == 3
    assert alice.post(f"/documents/{doc['id']}/retry").status_code == 409  # only failed documents
    # Re-extraction did not duplicate constraints.
    assert db.scalar(select(func.count()).select_from(ExtractedConstraint)) == 4


def test_transient_errors_are_retried_with_bounded_attempts(alice, hid, monkeypatch):
    real = processing.run_pipeline
    calls = {"n": 0}

    def flaky(job_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise processing.TransientJobError("provider rate limit")
        return real(job_id, **kw)

    monkeypatch.setattr(processing, "run_pipeline", flaky)
    doc, _ = upload(alice, hid, SBL_PDF)
    doc = alice.get(f"/documents/{doc['id']}").json()
    assert doc["status"] == "extracted" and doc["latest_job"]["attempt"] == 2

    def always(job_id, **kw):
        raise processing.TransientJobError("provider unreachable")

    monkeypatch.setattr(processing, "run_pipeline", always)
    doc2, _ = upload(alice, hid, make_pdf(["Other agreement"]))
    doc2 = alice.get(f"/documents/{doc2['id']}").json()
    assert doc2["status"] == "failed" and doc2["error_code"] == "retries_exhausted"
    assert doc2["latest_job"]["attempt"] == doc2["latest_job"]["max_attempts"]


def test_duplicate_delivery_is_ignored(alice, hid, db):
    doc, job = upload(alice, hid, SBL_PDF)
    assert processing.process_job(uuid.UUID(job["id"])) == "skipped"
    assert db.scalar(select(func.count()).select_from(ExtractedConstraint)) == 4


def test_llm_provider_path_with_mock(alice, hid, monkeypatch, db):
    """Mocked provider: verifies plumbing, schema validation and quote verification - not a live LLM call."""
    class MockProvider:
        name, model = "mock", "mock-model"

        def extract_json(self, system, user, schema):
            assert "<excerpt" in user and len(user) < 60_000  # bounded excerpts, not the whole document
            return {"terms": [
                {"excerpt_id": "p1-c0", "constraint_type": "sbl_maintenance_threshold", "asset_key": "sbl",
                 "description": "Maintenance threshold", "value": 60, "lower_bound": None, "upper_bound": None,
                 "unit": "% LTV", "timing": None, "conditions": None, "exceptions": [], "discretion": None,
                 "value_kind": "exact",
                 "evidence_quote": "If at any time the outstanding Loan Balance exceeds 60% of the market value of "
                                   "the Collateral", "interpretation": "LTV trigger", "confidence": "high",
                 "ambiguous": False},
                {"excerpt_id": "p1-c0", "constraint_type": "sbl_advance_rate", "asset_key": "sbl",
                 "description": "Invented", "value": 80, "lower_bound": None, "upper_bound": None, "unit": "%",
                 "timing": None, "conditions": None, "exceptions": [], "discretion": None, "value_kind": "exact", "evidence_quote": "The lender guarantees 80% at all times.",
                 "interpretation": "not in the document", "confidence": "high", "ambiguous": False}]}

    monkeypatch.setattr("app.services.processing.get_provider", lambda settings: MockProvider())
    doc, _ = upload(alice, hid, SBL_PDF)
    cons = {c["constraint_type"]: c for c in alice.get(f"/households/{hid}/constraints").json()}
    assert cons["sbl_maintenance_threshold"]["quote_verified"] is True
    assert cons["sbl_maintenance_threshold"]["provider"] == "mock"
    fake = cons["sbl_advance_rate"]
    assert fake["quote_verified"] is False and fake["confidence"] == "low"  # flagged for manual review


@pytest.mark.skipif(not ocr_available(), reason="tesseract not installed")
def test_scanned_pdf_is_read_with_ocr(alice, hid):
    src = pymupdf.open()
    src.new_page().insert_textbox(pymupdf.Rect(40, 40, 560, 300),
                                  "Capital calls require 10 business days notice.", fontsize=22)
    pix = src[0].get_pixmap(dpi=150)
    scanned = pymupdf.open()
    scanned.new_page(width=src[0].rect.width, height=src[0].rect.height).insert_image(src[0].rect, pixmap=pix)
    data = scanned.tobytes()
    doc, _ = upload(alice, hid, data, category="private_fund_agreement")
    doc = alice.get(f"/documents/{doc['id']}").json()
    assert doc["status"] == "extracted" and doc["ocr_pages"] == 1
    page = alice.get(f"/documents/{doc['id']}/pages/1").json()
    assert page["ocr"] is True and "business days" in page["text"]


def test_scanned_pdf_without_ocr_fails_clearly(alice, hid, monkeypatch):
    monkeypatch.setattr("app.services.ocr.ocr_available", lambda: False)
    blank = pymupdf.open()
    blank.new_page().draw_rect(pymupdf.Rect(50, 50, 200, 200), fill=(0, 0, 0))
    doc, _ = upload(alice, hid, blank.tobytes(), category="other")
    doc = alice.get(f"/documents/{doc['id']}").json()
    assert doc["status"] == "failed" and doc["error_code"] == "ocr_required"


def test_signed_download_and_tampering(alice, client, hid):
    doc, _ = upload(alice, hid, SBL_PDF)
    url = alice.get(f"/documents/{doc['id']}/download").json()["url"]
    r = client.get(url)
    assert r.status_code == 200 and r.content == SBL_PDF
    assert r.headers["cache-control"] == "no-store"
    tampered = url.replace("sig=", "sig=0")
    assert client.get(tampered).status_code == 404


def test_delete_follows_retention_policy(alice, hid, db, settings):
    doc, _ = upload(alice, hid, SBL_PDF)
    stored = db.get(Document, uuid.UUID(doc["id"]))
    file_path = Path(settings.local_storage_dir) / stored.storage_path
    assert file_path.exists()
    r = alice.delete(f"/documents/{doc['id']}")
    assert r.status_code == 200 and "audit" in r.json()["retention_policy"]
    db.expire_all()
    assert not file_path.exists()
    assert db.scalar(select(func.count()).select_from(DocumentPage)) == 0
    assert db.scalar(select(func.count()).select_from(ExtractedConstraint)) == 0
    row = db.get(Document, uuid.UUID(doc["id"]))
    assert row.status == "deleted" and row.storage_path is None and row.sha256 is None
    assert alice.get(f"/households/{hid}/documents").json()["total"] == 0
    assert alice.get(f"/documents/{doc['id']}/download").status_code == 404
    # The same file can be uploaded again after deletion.
    again, _ = upload(alice, hid, SBL_PDF)
    assert again["id"] != doc["id"] and again["status"] == "extracted"
    actions = [e["action"] for e in alice.get(f"/households/{hid}/audit-events").json()["items"]]
    assert "document.deleted" in actions
