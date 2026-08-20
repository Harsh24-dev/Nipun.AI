"""
Celery application — async task queue for document ingestion and scheduled jobs.
Broker + result backend: Redis (same instance as cache, different DB numbers).
"""

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    beat_init,
    task_failure,
    task_prerun,
    task_postrun,
    task_retry,
    worker_process_init,
    worker_ready,
    worker_shutdown,
)

from src.config import settings
from src.core.logging import setup_logging, trace_flow

log = structlog.get_logger("worker")

celery_app = Celery(
    "nipun_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "src.ingestion.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # re-queue on worker crash
    worker_prefetch_multiplier=1,  # one task at a time per worker (embedding is heavy)
    task_routes={
        "src.ingestion.tasks.process_document": {"queue": "ingestion.document"},
        "src.ingestion.tasks.update_realtime_data": {"queue": "ingestion.realtime"},
        "src.ingestion.tasks.batch_reindex": {"queue": "ingestion.document"},
    },
    beat_schedule={
        # Mandi prices — every 6 hours
        "update-mandi-prices": {
            "task": "src.ingestion.tasks.update_realtime_data",
            "schedule": crontab(minute=0, hour="*/6"),
            "args": ["mandi_prices"],
        },
        # Weather data — every 4 hours
        "update-weather": {
            "task": "src.ingestion.tasks.update_realtime_data",
            "schedule": crontab(minute=30, hour="*/4"),
            "args": ["weather"],
        },
        # Full scan for document updates — daily at 2am IST
        "daily-document-scan": {
            "task": "src.ingestion.tasks.batch_reindex",
            "schedule": crontab(minute=0, hour=2),
            "kwargs": {"domain": "all"},
        },
    },
)


# ── Worker lifecycle logging ──────────────────────────────────────────────────
# Celery runs tasks in separate processes with their own logging config, so each
# worker/beat process must call setup_logging() to write into our rotating files.

@worker_process_init.connect
def _init_worker_logging(**_kwargs) -> None:
    setup_logging()
    log.info("celery_worker_process_started")


@beat_init.connect
def _init_beat_logging(**_kwargs) -> None:
    setup_logging()
    log.info("celery_beat_started  scheduler=nipun_ai")


@worker_ready.connect
def _on_worker_ready(**_kwargs) -> None:
    log.info("celery_worker_ready")


@worker_shutdown.connect
def _on_worker_shutdown(**_kwargs) -> None:
    log.info("celery_worker_shutdown")


@task_prerun.connect
def _on_task_prerun(task_id=None, task=None, args=None, kwargs=None, **_kw) -> None:
    name = getattr(task, "name", "unknown")
    log.info("celery_task_start", task=name, task_id=task_id)
    trace_flow("celery_task_start", correlation_id=task_id or "", task=name,
               args=list(args or []), kwargs=dict(kwargs or {}))


@task_postrun.connect
def _on_task_postrun(task_id=None, task=None, retval=None, state=None, **_kw) -> None:
    name = getattr(task, "name", "unknown")
    log.info("celery_task_done", task=name, task_id=task_id, state=state)
    trace_flow("celery_task_done", correlation_id=task_id or "", task=name,
               state=state, result=retval)


@task_retry.connect
def _on_task_retry(request=None, reason=None, **_kw) -> None:
    log.warning("celery_task_retry", task=getattr(request, "task", "unknown"), reason=str(reason))


@task_failure.connect
def _on_task_failure(task_id=None, exception=None, sender=None, **_kw) -> None:
    name = getattr(sender, "name", "unknown")
    log.error("celery_task_failed", task=name, task_id=task_id, error=str(exception))
    trace_flow("celery_task_failed", correlation_id=task_id or "", task=name, error=str(exception))
