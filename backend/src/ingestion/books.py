"""
Book ingestion — download OPENLY-AVAILABLE full-text books, embed them locally
(BGE-M3), and index into Qdrant so the assistant answers from the actual book
content, not just titles.

Sources (public-domain / open only — copyrighted books are never downloaded):
  * Project Gutenberg via Gutendex API → plain-text full books.
  * Internet Archive open texts → `*_djvu.txt` full text / PDF.

The download → parse → chunk → local-embed → dual-write path reuses the existing
ingestion pipeline (`ingest_spec`), so book chunks land in the same
`{domain}_{language}` collections the retriever already searches.
"""

from __future__ import annotations

import os
import tempfile

import structlog

from src.config import settings
from src.core.logging import trace_flow
from src.ingestion.parser import _hash_content
from src.ingestion.pipeline import ingest_spec
from src.ingestion.sources.base import IngestSpec
from src.mcp.live.http import get_json

log = structlog.get_logger("ingestion.books")


# ── Discovery ─────────────────────────────────────────────────────────────────

async def _gutenberg(query: str, limit: int) -> list[dict]:
    """Project Gutenberg (public domain) via the Gutendex API."""
    data = await get_json("https://gutendex.com/books", params={"search": query})
    out: list[dict] = []
    for b in ((data or {}).get("results") or [])[:limit]:
        fmts = b.get("formats", {})
        url = (fmts.get("text/plain; charset=utf-8") or fmts.get("text/plain")
               or fmts.get("application/pdf"))
        if not url:
            continue
        out.append({
            "title": b.get("title", "")[:200],
            "url": url,
            "format": "pdf" if url.endswith(".pdf") else "txt",
            "source": "Project Gutenberg",
            "license": "public_domain",
            "authors": ", ".join(a.get("name", "") for a in b.get("authors", [])),
        })
    return out


async def _internet_archive(query: str, limit: int) -> list[dict]:
    """Internet Archive open texts — search, then resolve a text/PDF download URL."""
    search = await get_json(
        "https://archive.org/advancedsearch.php",
        params={"q": f'({query}) AND mediatype:texts', "fl[]": "identifier",
                "rows": limit, "output": "json", "sort[]": "downloads desc"},
    )
    docs = (((search or {}).get("response") or {}).get("docs")) or []
    out: list[dict] = []
    for d in docs[:limit]:
        ident = d.get("identifier")
        if not ident:
            continue
        meta = await get_json(f"https://archive.org/metadata/{ident}")
        if not meta or meta.get("is_dark"):
            continue
        files = meta.get("files") or []
        txt = next((f["name"] for f in files if f.get("name", "").endswith("_djvu.txt")), None)
        pdf = next((f["name"] for f in files if f.get("name", "").endswith(".pdf")), None)
        chosen, fmt = (txt, "txt") if txt else ((pdf, "pdf") if pdf else (None, None))
        if not chosen:
            continue
        title = (meta.get("metadata") or {}).get("title", ident)
        out.append({
            "title": (title if isinstance(title, str) else ident)[:200],
            "url": f"https://archive.org/download/{ident}/{chosen}",
            "format": fmt,
            "source": "Internet Archive",
            "license": "open_access",
            "authors": (meta.get("metadata") or {}).get("creator", ""),
        })
    return out


async def _openalex(query: str, limit: int) -> list[dict]:
    """OpenAlex (keyless) — open-access works/monographs with a direct PDF (oa_url)."""
    data = await get_json(
        "https://api.openalex.org/works",
        params={"search": query, "filter": "open_access.is_oa:true", "per_page": limit},
    )
    out: list[dict] = []
    for w in ((data or {}).get("results") or [])[:limit]:
        oa = (w.get("open_access") or {}).get("oa_url")
        if not oa:
            continue
        out.append({
            "title": (w.get("title") or "")[:200],
            "url": oa,
            "format": "pdf" if oa.lower().endswith(".pdf") else "txt",
            "source": "OpenAlex (open access)",
            "license": "open_access",
            "downloadable": True,
            "authors": ", ".join(a.get("author", {}).get("display_name", "")
                                 for a in (w.get("authorships") or [])[:2]),
        })
    return out


def _annas_archive_pointers(query: str) -> list[dict]:
    """Anna's Archive / LibGen — metadata 'where-to-find' pointers ONLY (no download).

    These indexes are mostly copyrighted; we surface a search link so a user can find a
    book, but never auto-download or embed copyrighted content (downloadable=False)."""
    from urllib.parse import quote_plus

    out: list[dict] = []
    if settings.ANNAS_ARCHIVE_ENABLED:
        out.append({
            "title": f"Find '{query}' on Anna's Archive",
            "url": f"{settings.ANNAS_ARCHIVE_BASE}/search?q={quote_plus(query)}",
            "format": "link", "source": "Anna's Archive", "license": "unknown",
            "downloadable": False, "authors": "",
        })
    if settings.LIBGEN_METADATA_ENABLED:
        out.append({
            "title": f"Find '{query}' on Library Genesis",
            "url": f"https://libgen.is/search.php?req={quote_plus(query)}",
            "format": "link", "source": "Library Genesis", "license": "unknown",
            "downloadable": False, "authors": "",
        })
    return out


def _is_open(license: str) -> bool:
    return (license or "").lower() in {l.lower() for l in settings.BOOKS_OPEN_LICENSES}


async def discover_book_sources(query: str, max_books: int | None = None) -> list[dict]:
    """Find full-text books for a topic. Openly-licensed sources (Gutenberg, Internet
    Archive, OpenAlex) are downloadable; Anna's Archive / LibGen are metadata-only
    'where-to-find' pointers (never auto-downloaded)."""
    limit = max_books or settings.BOOKS_INGEST_MAX
    results: list[dict] = []
    results += await _gutenberg(query, limit)
    if len(results) < limit:
        results += await _internet_archive(query, limit - len(results))
    if len(results) < limit:
        results += await _openalex(query, limit - len(results))
    # Metadata-only find-it pointers (copyrighted indexes) — appended, never downloaded.
    results += _annas_archive_pointers(query)
    # Normalise + de-dup by title.
    seen, out = set(), []
    for r in results:
        r.setdefault("downloadable", True)
        key = r["title"].lower()[:80]
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ── Download + ingest ─────────────────────────────────────────────────────────

async def _download_to_temp(url: str, suffix: str) -> str | None:
    """Stream a URL to a temp file, enforcing the size cap. Returns path or None."""
    import httpx

    max_bytes = settings.BOOKS_MAX_DOWNLOAD_MB * 1024 * 1024
    try:
        fd, path = tempfile.mkstemp(suffix=suffix)
        total = 0
        with os.fdopen(fd, "wb") as fh:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            log.warning("book_download_too_large", url=url[:120], mb=settings.BOOKS_MAX_DOWNLOAD_MB)
                            fh.close()
                            os.unlink(path)
                            return None
                        fh.write(chunk)
        return path
    except Exception as exc:
        log.warning("book_download_failed", url=url[:120], error=str(exc))
        return None


async def ingest_book(
    url: str, title: str, domain: str | None = None,
    language: str = "en", fmt: str = "txt", source: str = "", license: str = "",
    author: str = "",
) -> dict:
    """Download one open book and index it (local embeddings → Qdrant). Never raises."""
    dom = domain or settings.BOOKS_INGEST_DOMAIN
    book_id = f"book:{_hash_content(url)}"
    book_meta = {"kind": "book", "source": source or title, "source_site": source,
                 "license": license, "author": author, "book_id": book_id,
                 "visibility": "public"}
    log.info("book_ingest_start", title=title[:80], url=url[:120], fmt=fmt, domain=dom, source=source)
    trace_flow("book_ingest_start", title=title, url=url, fmt=fmt, domain=dom,
               source=source, license=license, author=author, book_id=book_id)

    tmp_path: str | None = None
    try:
        if fmt == "pdf" or url.lower().endswith(".pdf"):
            # PDFs must be a local file for parse_pdf; download first.
            tmp_path = await _download_to_temp(url, ".pdf")
            if not tmp_path:
                return {"status": "failed", "reason": "download_failed", "title": title}
            spec = IngestSpec(domain=dom, language=language, title=title,
                              source=tmp_path, source_url=url, metadata=book_meta)
        else:
            # Plain-text URL — the pipeline fetches + parses it directly.
            spec = IngestSpec(domain=dom, language=language, title=title,
                              source=url, source_url=url, metadata=book_meta)

        result = await ingest_spec(spec)
        log.info("book_ingest_done", title=title[:80], status=result.get("status"),
                 chunks=result.get("chunks", 0), domain=dom)
        trace_flow("book_ingest_done", title=title, status=result.get("status"),
                   chunks=result.get("chunks", 0), domain=dom, source_url=url)
        return result
    except Exception as exc:
        log.error("book_ingest_failed", title=title[:80], error=str(exc))
        return {"status": "failed", "reason": str(exc), "title": title}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def ingest_books_for_topic(
    topic: str, domain: str | None = None, language: str = "en", max_books: int | None = None,
) -> dict:
    """Discover + ingest the top open books for a topic. Returns a summary."""
    if not settings.BOOKS_INGEST_ENABLED:
        return {"topic": topic, "status": "disabled", "ingested": 0}

    sources = await discover_book_sources(topic, max_books)
    log.info("books_topic_discover", topic=topic, found=len(sources))
    trace_flow("books_topic_discover", topic=topic, found=len(sources),
               books=[{"title": s["title"], "source": s["source"], "url": s["url"]} for s in sources])

    ingested = 0
    chunks = 0
    details: list[dict] = []
    find_it: list[dict] = []
    for s in sources:
        # Licence gate: only openly-licensed, downloadable books are fetched + embedded.
        if not s.get("downloadable", True) or not _is_open(s.get("license", "")):
            find_it.append({"title": s["title"], "url": s["url"], "source": s.get("source", ""),
                            "reason": "not open-licensed — link only, not downloaded"})
            continue
        result = await ingest_book(
            url=s["url"], title=s["title"], domain=domain, language=language,
            fmt=s.get("format", "txt"), source=s.get("source", ""), license=s.get("license", ""),
            author=s.get("authors", ""),
        )
        details.append({"title": s["title"], "status": result.get("status"), "chunks": result.get("chunks", 0)})
        if result.get("status") == "success":
            ingested += 1
            chunks += result.get("chunks", 0)

    summary = {"topic": topic, "domain": domain or settings.BOOKS_INGEST_DOMAIN,
               "discovered": len(sources), "ingested": ingested, "chunks": chunks,
               "books": details, "find_it_links": find_it}
    log.info("books_topic_done", **{k: v for k, v in summary.items() if k not in ("books", "find_it_links")})
    return summary
