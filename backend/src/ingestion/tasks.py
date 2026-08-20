"""
Celery tasks for document ingestion pipeline.
Each task is idempotent — safe to retry on failure.
"""

import asyncio

import structlog

from src.core.logging import trace_flow
from src.ingestion.pipeline import ingest_spec
from src.ingestion.sources.base import IngestSpec
from src.worker.celery_app import celery_app

log = structlog.get_logger("ingestion.tasks")


def _run_async(coro):
    """Run async code inside a Celery task (sync context)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="src.ingestion.tasks.process_document",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def process_document(self, source: str, domain: str, language: str | None = None, title: str = ""):
    """
    Process and index a single document via the shared ingestion pipeline.
    source: file path (pdf/txt) or URL (http/https).
    """
    try:
        log.info("ingestion_job_started", source=source, domain=domain)
        trace_flow("celery_ingest_document", correlation_id=self.request.id or "",
                   source=source, domain=domain, language=language, title=title or source)
        spec = IngestSpec(
            domain=domain,
            language=language or "",
            title=title or source,
            source=source,
            source_url=source,
        )
        result = _run_async(ingest_spec(spec))
        trace_flow("celery_ingest_document_done", correlation_id=self.request.id or "",
                   source=source, domain=domain, result=result)
        return result
    except Exception as exc:
        log.error("ingestion_job_failed", source=source, error=str(exc), retry=self.request.retries)
        raise self.retry(exc=exc)


@celery_app.task(name="src.ingestion.tasks.ingest_domain")
def ingest_domain(domain: str, online: bool = False):
    """Ingest a whole domain's registered sources (seed pack + optional official URLs)."""
    from src.ingestion.run import ingest_domain as _ingest_domain

    log.info("domain_ingestion_started", domain=domain, online=online)
    return _run_async(_ingest_domain(domain, online=online))


@celery_app.task(name="src.ingestion.tasks.ingest_books_topic", bind=True, max_retries=2)
def ingest_books_topic(self, topic: str, domain: str | None = None,
                       language: str = "en", max_books: int | None = None):
    """Background: discover + download open full-text books for a topic, embed locally,
    and index into Qdrant so future queries answer from the actual book content."""
    from src.ingestion.books import ingest_books_for_topic

    log.info("books_ingest_task_started", topic=topic, domain=domain)
    trace_flow("celery_ingest_books", correlation_id=self.request.id or "",
               topic=topic, domain=domain, language=language)
    result = _run_async(ingest_books_for_topic(topic, domain=domain, language=language, max_books=max_books))
    trace_flow("celery_ingest_books_done", correlation_id=self.request.id or "",
               topic=topic, ingested=result.get("ingested"), chunks=result.get("chunks"))
    return result


@celery_app.task(name="src.ingestion.tasks.ingest_book_url", bind=True, max_retries=2)
def ingest_book_url(self, url: str, title: str, domain: str | None = None,
                    language: str = "en", fmt: str = "txt"):
    """Background: download + index one open book by URL."""
    from src.ingestion.books import ingest_book

    log.info("book_url_ingest_task_started", url=url, title=title)
    return _run_async(ingest_book(url=url, title=title, domain=domain, language=language, fmt=fmt))


@celery_app.task(name="src.ingestion.tasks.update_realtime_data")
def update_realtime_data(data_type: str):
    """Update time-sensitive data: mandi prices, weather."""
    log.info("realtime_update_started", data_type=data_type)
    # TODO: integrate Agmarknet API (mandi_prices) and IMD API (weather)
    # These will be wired when API keys are available
    log.info("realtime_update_complete", data_type=data_type)
    return {"status": "ok", "data_type": data_type}


@celery_app.task(name="src.ingestion.tasks.batch_reindex")
def batch_reindex(domain: str = "all"):
    """Trigger reindexing of all documents in a domain."""
    log.info("batch_reindex_started", domain=domain)
    # TODO: query document_index table and re-queue each document
    return {"status": "queued", "domain": domain}
