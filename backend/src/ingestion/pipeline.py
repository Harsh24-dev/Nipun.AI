"""
Shared async ingestion pipeline.

One implementation used by BOTH the CLI runner (`src.ingestion.run`) and the Celery
task (`src.ingestion.tasks.process_document`): resolve content → dedup → chunk →
dual-write index → record. Handles inline text, local files, and URLs.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from src.core.logging import trace_flow
from src.ingestion.chunker import chunk_text
from src.ingestion.indexer import index_document
from src.ingestion.parser import ParsedDocument, parse_html, parse_pdf, parse_text
from src.ingestion.sources.base import IngestSpec
from src.language.detector import detect_language

log = structlog.get_logger("ingestion.pipeline")


def _source_kind(spec: IngestSpec) -> str:
    """Classify where this document's content comes from (for logs)."""
    if spec.is_inline():
        return "inline_seed"
    src = spec.source or ""
    if src.startswith(("http://", "https://")):
        return "url"
    if src.endswith(".pdf"):
        return "pdf_file"
    return "text_file"


async def _check_dedup(source_url: str, source_hash: str) -> bool:
    from src.db.postgres import fetchrow

    row = await fetchrow(
        "SELECT id FROM document_index WHERE source_url = $1 AND source_hash = $2",
        source_url, source_hash,
    )
    return row is not None


async def _record_indexed(doc: ParsedDocument, chunk_count: int) -> None:
    from src.db.postgres import execute

    await execute(
        """
        INSERT INTO document_index (source_url, source_hash, domain, language, title, chunk_count)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (source_url, source_hash) DO NOTHING
        """,
        doc.source_url, doc.source_hash, doc.domain, doc.language, doc.title, chunk_count,
    )


def _resolve_document(spec: IngestSpec) -> ParsedDocument:
    """Turn an IngestSpec into a ParsedDocument (fetches URLs, reads files)."""
    if spec.is_inline():
        doc = parse_text(spec.text or "", spec.title, spec.domain, spec.language,
                         source_url=spec.source_url or spec.title)
    elif spec.source and (spec.source.startswith("http://") or spec.source.startswith("https://")):
        import httpx

        resp = httpx.get(spec.source, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        if "html" in resp.headers.get("content-type", ""):
            doc = parse_html(resp.text, spec.domain, spec.language, source_url=spec.source)
        else:
            doc = parse_text(resp.text, spec.title or spec.source, spec.domain, spec.language,
                             source_url=spec.source)
    elif spec.source and spec.source.endswith(".pdf"):
        doc = parse_pdf(spec.source, spec.domain, spec.language, source_url=spec.source_url or spec.source)
    elif spec.source:
        doc = parse_text(Path(spec.source).read_text(encoding="utf-8"), spec.title or spec.source,
                         spec.domain, spec.language, source_url=spec.source_url or spec.source)
    else:
        raise ValueError(f"IngestSpec has neither text nor source: {spec.title}")

    if not spec.language:
        doc.language = detect_language(doc.text[:500])
    # Carry the source spec's rich metadata (author/subject/level/book_id/license/kind)
    # onto the parsed doc so the indexer can write it into each chunk's payload.
    if spec.metadata:
        doc.metadata = {**(doc.metadata or {}), **spec.metadata}
    if spec.section and not doc.metadata.get("section"):
        doc.metadata["section"] = spec.section
    return doc


async def ingest_spec(spec: IngestSpec, skip_dedup: bool = False) -> dict:
    """Ingest one document. Returns a status dict; never raises on empty content."""
    kind = _source_kind(spec)
    log.info("ingestion_doc_start", title=spec.title, domain=spec.domain, kind=kind,
             source=spec.source or spec.source_url)
    doc = _resolve_document(spec)
    # Full detail of the document being ingested: where it came from + how big it is.
    trace_flow(
        "ingestion_document_resolved",
        title=doc.title,
        domain=doc.domain,
        language=doc.language,
        kind=kind,
        source=spec.source or "(inline)",
        source_url=doc.source_url,
        source_hash=doc.source_hash,
        char_count=len(doc.text or ""),
    )

    # Persist the parsed text + a manifest entry to local disk (only when
    # NIPUN_ARCHIVE_CORPUS=1) so this exact corpus can be re-ingested in production.
    # Done BEFORE the dedup gate so a re-run still captures every file locally.
    if (doc.text or "").strip():
        from src.ingestion.archive import archive_document

        archive_document(doc)

    if not skip_dedup and await _check_dedup(doc.source_url, doc.source_hash):
        log.info("ingestion_skipped_dedup", title=doc.title, domain=doc.domain)
        return {"status": "skipped", "reason": "already_indexed", "title": doc.title}

    chunks = chunk_text(doc.text)
    if not chunks:
        return {"status": "skipped", "reason": "no_content", "title": doc.title}

    chunk_count = await index_document(doc, chunks)
    await _record_indexed(doc, chunk_count)
    log.info("ingestion_job_complete", title=doc.title, domain=doc.domain, chunks=chunk_count)
    trace_flow(
        "ingestion_document_indexed",
        title=doc.title,
        domain=doc.domain,
        language=doc.language,
        source_url=doc.source_url,
        chunks=chunk_count,
    )
    return {"status": "success", "chunks": chunk_count, "title": doc.title, "domain": doc.domain}
