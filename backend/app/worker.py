"""Celery application and tasks (document processing, export generation).

Run:  celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2
"""
from __future__ import annotations

import logging
import uuid

from celery import Celery

from .config import get_settings
from .logging_config import configure_logging

configure_logging()
log = logging.getLogger("slipslopes.worker")
_settings = get_settings()

celery_app = Celery("slipslopes", broker=_settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,                 # a crashed worker's task is redelivered...
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,             # status lives in PostgreSQL, not the result backend
    task_soft_time_limit=_settings.processing_time_limit_s,
    task_time_limit=_settings.processing_time_limit_s + 60,
    task_always_eager=_settings.celery_task_always_eager,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
    task_default_queue="slipslopes",
)


@celery_app.task(name="slipslopes.process_document", bind=True)
def process_document(self, job_id: str) -> str:
    # ...and claim_job() makes redelivery safe: only a 'queued' job is processed.
    from .services.processing import process_job

    status = process_job(uuid.UUID(job_id))
    if status == "retry":
        from .db import session_scope
        from .models import ProcessingJob

        with session_scope() as db:
            job = db.get(ProcessingJob, uuid.UUID(job_id))
            attempt = job.attempt if job else 1
        countdown = min(300, 15 * 2 ** (attempt - 1))
        if not celery_app.conf.task_always_eager:
            process_document.apply_async(args=[job_id], countdown=countdown)
        else:
            process_document.apply(args=[job_id])
    log.info("process_document job=%s status=%s", job_id, status)
    return status


@celery_app.task(name="slipslopes.generate_export")
def generate_export(export_id: str) -> str:
    from .services.exports import build_export

    return build_export(uuid.UUID(export_id))


def enqueue_processing(job_id: uuid.UUID) -> str | None:
    result = process_document.apply_async(args=[str(job_id)])
    return getattr(result, "id", None)


def enqueue_export(export_id: uuid.UUID) -> None:
    generate_export.apply_async(args=[str(export_id)])
