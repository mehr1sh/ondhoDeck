"""Document upload lifecycle, processing jobs, evidence pages, downloads and deletion."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..api_schemas import (
    DocumentInitiate,
    DocumentInitiateOut,
    DocumentOut,
    JobOut,
    Page,
    PageOut,
    SignedUrlOut,
    UploadTarget,
)
from ..audit import audit
from ..auth import CurrentUser, get_current_user
from ..authz import require_fund, require_household, require_owned
from ..config import Settings, get_settings
from ..db import get_db
from ..errors import ApiError
from ..models import Document, DocumentPage, ExtractedConstraint, ProcessingJob
from ..ratelimit import check_rate
from ..services.documents import RETENTION_POLICY, create_job, purge_document, store_document
from ..services.pdf_validation import validate_pdf
from ..storage import LocalStorage, get_storage, safe_filename
from .common import Pagination, paginate

router = APIRouter(tags=["documents"])


def document_out(db: Session, doc: Document) -> DocumentOut:
    job = db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == doc.id)
                     .order_by(ProcessingJob.created_at.desc()).limit(1)).first()
    count = db.scalar(select(func.count()).select_from(ExtractedConstraint)
                      .where(ExtractedConstraint.document_id == doc.id)) or 0
    out = DocumentOut.model_validate(doc)
    return out.model_copy(update={"latest_job": JobOut.model_validate(job) if job else None, "constraint_count": count})


def _enqueue(job: ProcessingJob) -> None:
    from ..worker import enqueue_processing
    enqueue_processing(job.id)


@router.get("/households/{household_id}/documents", response_model=Page[DocumentOut])
def list_documents(household_id: uuid.UUID, p: Pagination = Depends(), include_deleted: bool = False,
                   user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    require_household(db, user, household_id)
    stmt = select(Document).where(Document.household_id == household_id)
    if not include_deleted:
        stmt = stmt.where(Document.status != "deleted")
    rows, total = paginate(db, stmt.order_by(Document.created_at.desc()), p)
    return Page(items=[document_out(db, r[0]) for r in rows], total=total, limit=p.limit, offset=p.offset)


def initiate_document(db: Session, user: CurrentUser, settings: Settings, *, filename: str, category: str,
                      size_bytes: int, sha256: Optional[str], household_id: Optional[uuid.UUID] = None,
                      fund_id: Optional[uuid.UUID] = None, effective_date: Optional[date] = None,
                      supersedes_document_id: Optional[uuid.UUID] = None) -> DocumentInitiateOut:
    """Create a pending document for exactly one owner (household or library fund); caller authorizes."""
    if not filename.lower().endswith(".pdf"):
        raise ApiError(415, "unsupported_media_type", "Only PDF documents are accepted.")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ApiError(413, "payload_too_large", f"Files must be {settings.max_upload_mb} MB or smaller.")
    owner = (Document.fund_id == fund_id) if fund_id is not None else (Document.household_id == household_id)
    if sha256:
        existing = db.scalar(select(Document).where(owner, Document.sha256 == sha256, Document.deleted_at.is_(None)))
        if existing is not None:
            return DocumentInitiateOut(document=document_out(db, existing), upload=None, duplicate=True)
    doc = Document(household_id=household_id, fund_id=fund_id, uploaded_by=user.id, category=category,
                   original_filename=filename[:255], safe_filename=safe_filename(filename),
                   storage_bucket=settings.storage_bucket, status="pending_upload", effective_date=effective_date,
                   supersedes_document_id=supersedes_document_id)
    db.add(doc)
    db.flush()
    audit(db, actor_id=user.id, action="document.upload_initiated", entity_type="document", entity_id=doc.id,
          household_id=household_id, fund_id=fund_id, details={"category": category, "size_bytes": size_bytes})
    db.commit()
    return DocumentInitiateOut(document=document_out(db, doc), duplicate=False,
                               upload=UploadTarget(url=f"/api/v1/documents/{doc.id}/content", max_bytes=max_bytes))


@router.post("/households/{household_id}/documents", response_model=DocumentInitiateOut, status_code=201)
def initiate_upload(household_id: uuid.UUID, body: DocumentInitiate, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    require_household(db, user, household_id, "editor")
    return initiate_document(db, user, settings, filename=body.filename, category=body.category,
                             size_bytes=body.size_bytes, sha256=body.sha256, household_id=household_id)


@router.put("/documents/{document_id}/content", response_model=DocumentOut)
async def upload_content(document_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                         db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    doc = require_owned(db, user, Document, document_id, "editor", "Document")
    if doc.status != "pending_upload":
        if doc.status == "deleted":
            raise ApiError(404, "not_found", "Document not found.")
        return document_out(db, doc)  # idempotent: content already received
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in ("application/pdf", "application/octet-stream"):
        raise ApiError(415, "unsupported_media_type", "Send the file as application/pdf.")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise ApiError(413, "payload_too_large", f"Files must be {settings.max_upload_mb} MB or smaller.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise ApiError(413, "payload_too_large", f"Files must be {settings.max_upload_mb} MB or smaller.")
        chunks.append(chunk)
    data = b"".join(chunks)
    validated = validate_pdf(data, settings)
    store_document(db, get_storage(), doc, data, validated)
    audit(db, actor_id=user.id, action="document.uploaded", entity_type="document", entity_id=doc.id,
          household_id=doc.household_id, fund_id=doc.fund_id,
          details={"pages": validated.page_count, "size_bytes": validated.size_bytes})
    db.commit()
    return document_out(db, doc)


@router.post("/documents/{document_id}/complete", response_model=JobOut, status_code=202)
def complete_upload(document_id: uuid.UUID, idempotency_key: Optional[str] = Header(None, max_length=100),
                    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)):
    doc = require_owned(db, user, Document, document_id, "editor", "Document")
    if doc.status == "pending_upload":
        raise ApiError(409, "conflict", "Upload the file content before completing the upload.")
    if doc.status == "deleted":
        raise ApiError(404, "not_found", "Document not found.")
    existing = db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == doc.id)
                          .order_by(ProcessingJob.created_at.desc())).first()
    if existing is not None and idempotency_key is None:
        return existing  # completing twice never starts a second extraction
    check_rate(str(user.id), "extraction", settings.rate_limit_extraction_per_hour, 3600)
    job, created = create_job(db, doc, settings, f"{doc.id}:{idempotency_key or 'initial'}", user.id)
    if created:
        audit(db, actor_id=user.id, action="document.processing_requested", entity_type="document",
              entity_id=doc.id, household_id=doc.household_id, fund_id=doc.fund_id)
    db.commit()
    if created:
        _enqueue(job)
        db.refresh(job)
    return job


@router.post("/documents/{document_id}/retry", response_model=JobOut, status_code=202)
def retry_processing(document_id: uuid.UUID, idempotency_key: Optional[str] = Header(None, max_length=100),
                     user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings)):
    doc = require_owned(db, user, Document, document_id, "editor", "Document")
    latest = db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == doc.id)
                        .order_by(ProcessingJob.created_at.desc())).first()
    if idempotency_key:
        prior = db.scalar(select(ProcessingJob).where(
            ProcessingJob.idempotency_key == f"{doc.id}:retry:{idempotency_key}"))
        if prior is not None:
            return prior
    if doc.status != "failed" or latest is None or latest.status != "failed":
        raise ApiError(409, "conflict", "Only a failed document can be retried.")
    check_rate(str(user.id), "extraction", settings.rate_limit_extraction_per_hour, 3600)
    key = f"{doc.id}:retry:{idempotency_key or latest.id}"
    job, created = create_job(db, doc, settings, key, user.id)
    if created:
        audit(db, actor_id=user.id, action="document.retry_requested", entity_type="document", entity_id=doc.id,
              household_id=doc.household_id, fund_id=doc.fund_id, details={"previous_job": str(latest.id)})
    db.commit()
    if created:
        _enqueue(job)
        db.refresh(job)
    return job


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return document_out(db, require_owned(db, user, Document, document_id, label="Document"))


@router.get("/documents/{document_id}/jobs", response_model=list[JobOut])
def list_jobs(document_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = require_owned(db, user, Document, document_id, label="Document")
    return db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == doc.id)
                      .order_by(ProcessingJob.created_at.desc())).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return require_owned(db, user, ProcessingJob, job_id, label="Job")


@router.get("/documents/{document_id}/download", response_model=SignedUrlOut)
def download_document(document_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    doc = require_owned(db, user, Document, document_id, label="Document")
    if not doc.storage_path or doc.status == "deleted":
        raise ApiError(404, "not_found", "No stored file for this document.")
    url = get_storage().signed_url(doc.storage_path, settings.signed_url_ttl_seconds, doc.safe_filename)
    audit(db, actor_id=user.id, action="document.downloaded", entity_type="document", entity_id=doc.id,
          household_id=doc.household_id, fund_id=doc.fund_id)
    db.commit()
    return SignedUrlOut(url=url, expires_in=settings.signed_url_ttl_seconds)


@router.get("/documents/{document_id}/pages/{pdf_page}", response_model=PageOut)
def get_page(document_id: uuid.UUID, pdf_page: int, user: CurrentUser = Depends(get_current_user),
             db: Session = Depends(get_db)):
    doc = require_owned(db, user, Document, document_id, label="Document")
    page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id, DocumentPage.pdf_page == pdf_page))
    if page is None:
        raise ApiError(404, "not_found", "No extracted text for this page.")
    return PageOut(document_id=doc.id, pdf_page=page.pdf_page, printed_page=page.printed_page, section=page.section,
                   ocr=page.ocr, text=page.text)


@router.delete("/documents/{document_id}", status_code=200)
def delete_document(document_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    doc = require_owned(db, user, Document, document_id, "editor", "Document")
    if doc.status == "deleted":
        return {"deleted": True, "retention_policy": RETENTION_POLICY}
    if doc.fund_id is not None:
        # Shared library: reviewer only, and never once a term was approved (other households may rely on it).
        require_fund(db, user, doc.fund_id, "reviewer")
        approved = db.scalar(select(func.count()).select_from(ExtractedConstraint).where(
            ExtractedConstraint.document_id == doc.id, ExtractedConstraint.review_status.in_(("confirmed", "edited"))))
        if approved:
            raise ApiError(409, "conflict", f"{approved} approved term(s) come from this library document, so it "
                                            "cannot be deleted. Upload the replacement and mark its terms as "
                                            "superseding these instead.")
    purge_document(db, get_storage(), doc)
    audit(db, actor_id=user.id, action="document.deleted", entity_type="document", entity_id=doc.id,
          household_id=doc.household_id, fund_id=doc.fund_id)
    db.commit()
    return {"deleted": True, "retention_policy": RETENTION_POLICY}


@router.get("/local-storage/{path:path}", include_in_schema=False)
def local_storage_download(path: str, expires: int = Query(...), sig: str = Query(...),
                           download: str = Query("document.pdf")):
    """Development-only signed download for LocalStorage (Supabase serves signed URLs in production)."""
    storage = get_storage()
    if not isinstance(storage, LocalStorage) or not storage.verify(path, expires, sig):
        raise ApiError(404, "not_found", "Not found.")
    data = storage.get(path)
    ctype = "application/pdf" if path.endswith(".pdf") else "application/octet-stream"
    name = safe_filename(download) if download.endswith(".pdf") else download.replace('"', "")
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                     "Cache-Control": "no-store"})
