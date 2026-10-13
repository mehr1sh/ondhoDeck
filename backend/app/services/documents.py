"""Document storage, job creation and the deletion/retention policy."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ApiError
from ..models import Document, DocumentPage, ExportRecord, ExtractedConstraint, ProcessingJob
from ..storage import Storage, StorageError
from .pdf_validation import ValidatedPdf

log = logging.getLogger("slipslopes.documents")

RETENTION_POLICY = (
    "Deleting a document immediately removes the stored PDF from private storage, its extracted page text and "
    "all constraints extracted from it. A minimal record (file name, size, timestamps, status 'deleted') is kept "
    "for the audit trail. Simulation runs keep their own snapshot of the contract terms and citations they used."
)


def storage_path_for(doc: Document) -> str:
    return f"{doc.household_id}/documents/{doc.id}/{doc.safe_filename}"


def store_document(db: Session, storage: Storage, doc: Document, data: bytes, v: ValidatedPdf) -> None:
    """Write validated bytes to private storage and mark the document uploaded (caller commits)."""
    duplicate = db.scalar(select(Document).where(Document.household_id == doc.household_id,
                                                 Document.sha256 == v.sha256, Document.deleted_at.is_(None),
                                                 Document.id != doc.id))
    if duplicate is not None:
        raise ApiError(409, "conflict", "This household already has an identical document.",
                       details={"existing_document_id": str(duplicate.id)})
    path = storage_path_for(doc)
    try:
        storage.put(path, data, "application/pdf")
    except StorageError as exc:
        raise ApiError(503, "storage_unavailable", "The file could not be stored. Please try again.") from exc
    doc.storage_path, doc.sha256, doc.size_bytes, doc.page_count = path, v.sha256, v.size_bytes, v.page_count
    doc.status = "uploaded"


def create_job(db: Session, doc: Document, settings: Settings, idempotency_key: str) -> tuple[ProcessingJob, bool]:
    """Create a queued job (idempotent by key / one active job per document). Returns (job, created)."""
    existing = db.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == idempotency_key))
    if existing is not None:
        return existing, False
    active = db.scalar(select(ProcessingJob).where(ProcessingJob.document_id == doc.id,
                                                   ProcessingJob.status.in_(("queued", "running"))))
    if active is not None:
        return active, False
    previous = db.scalars(select(ProcessingJob).where(ProcessingJob.document_id == doc.id)).all()
    job = ProcessingJob(document_id=doc.id, household_id=doc.household_id, status="queued",
                        attempt=1, max_attempts=settings.max_job_attempts, idempotency_key=idempotency_key,
                        stats={"run_number": len(previous) + 1})
    db.add(job)
    doc.status, doc.error_code, doc.error_message = "queued", None, None
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent duplicate request
        db.rollback()
        raise ApiError(409, "conflict", "Processing is already in progress for this document.") from exc
    return job, True


def purge_document(db: Session, storage: Storage, doc: Document) -> None:
    """Apply the retention policy (caller commits). Storage deletion failures are logged and retried by delete."""
    paths = [doc.storage_path] if doc.storage_path else []
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
    db.execute(delete(ExtractedConstraint).where(ExtractedConstraint.document_id == doc.id))
    doc.status, doc.deleted_at = "deleted", datetime.now(UTC)
    doc.storage_path, doc.sha256 = None, None
    doc.original_filename = doc.safe_filename
    try:
        storage.delete(paths)
    except StorageError:
        log.warning("storage delete failed for document %s", doc.id)
        raise ApiError(503, "storage_unavailable", "The file could not be deleted from storage. Please retry.")


def purge_household_files(db: Session, storage: Storage, household_id: uuid.UUID) -> None:
    docs = db.scalars(select(Document).where(Document.household_id == household_id)).all()
    exports = db.scalars(select(ExportRecord).where(ExportRecord.household_id == household_id)).all()
    paths = [d.storage_path for d in docs if d.storage_path] + [e.storage_path for e in exports if e.storage_path]
    try:
        storage.delete(paths)
    except StorageError as exc:
        raise ApiError(503, "storage_unavailable", "Stored files could not be deleted. Please retry.") from exc
