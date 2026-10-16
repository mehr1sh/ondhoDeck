"""Document-processing pipeline executed by the background worker.

download (private storage) -> parse pages (PyMuPDF) -> OCR pages without text -> retrieve bounded
excerpts -> extract (LLM provider, or deterministic rules when none is configured) -> verify quotes
against page text -> persist pages + draft constraints atomically.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..crypto import CredentialDecryptionError, CredentialStorageUnavailable, get_cipher
from ..db import session_scope
from ..engine.constraint_extractor import extract_rule_based, extract_with_llm
from ..engine.document_parser import PageText, ParsedDocument, detect_printed_page, parse_pdf_bytes
from ..engine.llm_service import LLMError
from ..engine.schemas import ContractConstraint, ExtractionMethod
from ..llm import LLMProvider, ProviderError, TransientProviderError, build_provider, get_provider
from ..models import Document, DocumentPage, ExtractedConstraint, ProcessingJob, ProviderCredential
from ..storage import Storage, StorageError, get_storage
from .ocr import ocr_pages

log = logging.getLogger("slipslopes.processing")


class TransientJobError(RuntimeError):
    """Retry the job later (storage/provider hiccup)."""


@dataclass
class JobFailure(Exception):
    code: str
    message: str


def _now() -> datetime:
    return datetime.now(UTC)


def _set_stage(job_id: uuid.UUID, stage: str, progress: int) -> None:
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        if job is not None:
            job.stage, job.progress = stage, progress


def claim_job(job_id: uuid.UUID) -> bool:
    """Atomically move a queued job to running. False if it is not claimable (duplicate delivery)."""
    with session_scope() as db:
        job = db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()).scalar_one_or_none()
        if job is None or job.status != "queued":
            return False
        job.status, job.started_at, job.stage, job.progress = "running", _now(), "downloading", 5
        job.error_code = job.error_message = None
        doc = db.get(Document, job.document_id)
        if doc is None or doc.status == "deleted":
            job.status, job.finished_at = "failed", _now()
            job.error_code, job.error_message = "document_deleted", "The document was deleted before processing."
            return False
        doc.status = "processing"
        return True


def _extraction_key(c: ContractConstraint, method: ExtractionMethod) -> str:
    if method == ExtractionMethod.RULE_BASED:
        return "rule:" + c.constraint_id.split(":", 1)[-1]
    digest = hashlib.sha1(f"{c.constraint_type.value}|{c.asset_key.value}|{c.evidence_quote}".encode()).hexdigest()
    return f"llm:{c.constraint_type.value}:{digest[:16]}"


def _dec(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _redact(message: str, provider_obj: object) -> str:
    """Never let a credential reach a job record or log, whatever an error message contains."""
    secret = getattr(provider_obj, "api_key", "") or ""
    return message.replace(secret, "[redacted]") if len(secret) >= 8 else message


def resolve_provider(db: Session, requested_by: uuid.UUID | None,
                     settings: Settings) -> tuple[LLMProvider | None, str]:
    """Choose the extraction provider for a job: the requester's active BYOK key, else the server provider,
    else none (rule-based). The decrypted key exists only in this worker process's memory."""
    if requested_by is not None:
        cred = db.scalar(select(ProviderCredential).where(ProviderCredential.user_id == requested_by,
                                                          ProviderCredential.is_active.is_(True)))
        if cred is not None and cred.status != "invalid":
            try:
                secret = get_cipher().decrypt(cred.ciphertext, owner=str(requested_by), provider=cred.provider)
            except (CredentialStorageUnavailable, CredentialDecryptionError) as exc:
                raise JobFailure("credential_unusable", "Your stored AI provider key could not be used. Replace it "
                                 "in AI provider settings or deactivate it.") from exc
            if cred.provider == "openai" and not cred.model:
                raise JobFailure("model_required", "Choose an OpenAI model in AI provider settings.")
            return build_provider(cred.provider, secret, cred.model, settings,
                                  workspace_id=cred.workspace_id), "user_byok"
    server = get_provider(settings)
    return (server, "server") if server is not None else (None, "none")


def run_pipeline(job_id: uuid.UUID, *, settings: Settings | None = None, storage: Storage | None = None,
                 provider: LLMProvider | None | bool = True) -> None:
    """Process a claimed (running) job. Raises TransientJobError or JobFailure; persists on success."""
    settings = settings or get_settings()
    storage = storage or get_storage()
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        doc = db.get(Document, job.document_id) if job else None
        if job is None or doc is None or not doc.storage_path:
            raise JobFailure("missing_document", "The document has no stored file.")
        storage_path, display_name, doc_id = doc.storage_path, doc.safe_filename, doc.id
        if provider is True:
            provider_obj, credential_source = resolve_provider(db, job.requested_by, settings)
        else:
            provider_obj, credential_source = (provider or None), ("injected" if provider else "none")

    try:
        data = storage.get(storage_path)
    except StorageError as exc:
        raise TransientJobError("storage download failed") from exc

    _set_stage(job_id, "parsing", 20)
    parsed: ParsedDocument = parse_pdf_bytes(data, display_name)
    if parsed.errors and not parsed.pages and not parsed.failed_pages:
        raise JobFailure("unreadable_pdf", "The PDF could not be parsed.")
    parsed.document_id = str(doc_id)

    ocr_used: list[int] = []
    if parsed.failed_pages:
        if settings.ocr_enabled:
            _set_stage(job_id, "ocr", 35)
            ocr = ocr_pages(data, parsed.failed_pages, settings.ocr_max_pages)
            for n, text in ocr.texts.items():
                parsed.pages.append(PageText(pdf_page=n, text=text, printed_page=detect_printed_page(text)))
                ocr_used.append(n)
            parsed.pages.sort(key=lambda p: p.pdf_page)
            parsed.failed_pages = [n for n in parsed.failed_pages if n not in ocr.texts]
            if not parsed.pages:
                if not ocr.available:
                    raise JobFailure("ocr_required", "No text layer was found and OCR is not available on this "
                                                     "server. Upload a text-based PDF or enable OCR.")
                raise JobFailure("ocr_failed", "No text layer was found and OCR could not read the pages.")
        elif not parsed.pages:
            raise JobFailure("ocr_required", "No text layer was found and OCR is disabled.")

    _set_stage(job_id, "extracting", 55)
    method = ExtractionMethod.LLM if provider_obj else ExtractionMethod.RULE_BASED
    # Record what is being attempted before calling the provider, so a failed AI job is distinguishable from a
    # rule-based run (credential_source "none") and from a successful AI extraction (status "succeeded").
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        if job is not None:
            job.extraction_method = method.value
            job.provider = provider_obj.name if provider_obj else None
            job.model = provider_obj.model if provider_obj else None
            job.credential_source = credential_source
    try:
        if provider_obj is not None:
            report = extract_with_llm(parsed, top_k=settings.llm_max_excerpts, call=provider_obj.extract_json)
        else:
            report = extract_rule_based(parsed)
    except TransientProviderError as exc:
        raise TransientJobError(_redact(str(exc), provider_obj)) from None
    except (ProviderError, LLMError) as exc:
        code = getattr(exc, "code", None) or "extraction_failed"
        raise JobFailure(code, _redact(f"Extraction failed: {exc}", provider_obj)[:480]) from None

    _set_stage(job_id, "saving", 85)
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        doc = db.get(Document, doc_id)
        if job is None or doc is None or doc.status == "deleted":
            raise JobFailure("document_deleted", "The document was deleted during processing.")
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc_id))
        db.add_all([DocumentPage(document_id=doc_id, household_id=doc.household_id, fund_id=doc.fund_id,
                                 pdf_page=p.pdf_page, printed_page=p.printed_page, section=p.section,
                                 text=p.text.replace("\x00", ""), ocr=p.pdf_page in ocr_used) for p in parsed.pages])
        existing = {c.extraction_key: c for c in db.scalars(
            select(ExtractedConstraint).where(ExtractedConstraint.document_id == doc_id))}
        written = kept = 0
        for c in report.constraints:
            key = _extraction_key(c, method)
            row = existing.get(key)
            if row is not None and row.review_status != "needs_review":
                kept += 1  # never overwrite a reviewed constraint
                continue
            values = dict(
                household_id=doc.household_id, fund_id=doc.fund_id, document_id=doc_id, job_id=job_id,
                extraction_key=key,
                constraint_type=c.constraint_type.value, asset_key=c.asset_key.value, description=c.description,
                value=_dec(c.value), lower_bound=_dec(c.lower_bound), upper_bound=_dec(c.upper_bound),
                original_value=_dec(c.value), unit=c.unit, timing=c.timing, conditions=c.conditions,
                pdf_page=c.pdf_page, printed_page=c.printed_page, document_section=c.document_section,
                evidence_quote=c.evidence_quote, quote_verified=c.quote_verified,
                corroborating_pages=c.corroborating_pages, interpretation=c.interpretation,
                value_kind=c.value_kind.value if c.value_kind else None, exceptions=list(c.exceptions),
                discretion=c.discretion, effective_period=c.timing, ambiguous=c.ambiguous,
                validation_issues=list(c.validation_issues),
                confidence=c.confidence.value, source_type=c.source_type.value, review_status="needs_review",
                extraction_method=method.value,
                provider=provider_obj.name if provider_obj else None,
                model=provider_obj.model if provider_obj else None)
            if row is None:
                db.add(ExtractedConstraint(revision=1, **values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
            written += 1
        doc.status, doc.page_count = "extracted", parsed.page_count
        doc.pages_without_text, doc.ocr_pages = len(parsed.failed_pages), len(ocr_used)
        doc.error_code = doc.error_message = None
        job.status, job.progress, job.stage, job.finished_at = "succeeded", 100, "done", _now()
        job.extraction_method = method.value
        job.provider = provider_obj.name if provider_obj else None
        job.model = provider_obj.model if provider_obj else None
        job.credential_source = credential_source
        usage = getattr(provider_obj, "last_usage", None)
        job.stats = {"llm_input_tokens": getattr(usage, "input_tokens", None),
                     "llm_output_tokens": getattr(usage, "output_tokens", None),
                     "llm_latency_ms": getattr(provider_obj, "last_latency_ms", None),
                     "ambiguous_constraints": sum(c.ambiguous for c in report.constraints),
                     "constraints_with_validation_issues": sum(bool(c.validation_issues) for c in report.constraints),
                     "pages": parsed.page_count, "pages_with_text": len(parsed.pages), "ocr_pages": len(ocr_used),
                     "pages_without_text": len(parsed.failed_pages), "excerpts_used": report.excerpts_used,
                     "constraints_written": written, "reviewed_constraints_kept": kept,
                     "unverified_quotes": sum(not c.quote_verified for c in report.constraints),
                     "messages": report.messages[:5]}


def mark_failed(job_id: uuid.UUID, code: str, message: str) -> None:
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            return
        job.status, job.finished_at, job.error_code, job.error_message = "failed", _now(), code, message[:480]
        doc = db.get(Document, job.document_id)
        if doc is not None and doc.status != "deleted":
            doc.status, doc.error_code, doc.error_message = "failed", code, message[:480]


def requeue_for_retry(job_id: uuid.UUID, reason: str) -> bool:
    """Bounded automatic retry of a transient failure. Returns False when attempts are exhausted."""
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.attempt >= job.max_attempts:
            return False
        job.attempt += 1
        job.status, job.stage, job.progress = "queued", "waiting_to_retry", 0
        job.error_code, job.error_message = "transient_error", reason[:480]
        doc = db.get(Document, job.document_id)
        if doc is not None and doc.status != "deleted":
            doc.status = "queued"
        return True


def process_job(job_id: uuid.UUID, **kwargs) -> str:
    """Entry point used by the Celery task. Returns the resulting job status."""
    if not claim_job(job_id):
        return "skipped"
    try:
        run_pipeline(job_id, **kwargs)
        return "succeeded"
    except TransientJobError as exc:
        if requeue_for_retry(job_id, str(exc)):
            return "retry"
        mark_failed(job_id, "retries_exhausted", f"Gave up after repeated temporary errors ({exc}).")
        return "failed"
    except JobFailure as exc:
        mark_failed(job_id, exc.code, exc.message)
        return "failed"
    except SoftTimeLimitExceeded:
        mark_failed(job_id, "timeout", "Processing exceeded the time limit. Try a smaller document or retry.")
        return "failed"
    except Exception:
        log.exception("unexpected processing error job_id=%s", job_id)
        mark_failed(job_id, "internal_error", "An unexpected error occurred while processing the document.")
        return "failed"
