"""
Corpus archiver — persist every ingested document to local disk so the exact same
corpus can be re-uploaded/re-ingested in another environment (e.g. production).

For each indexed document we save the PARSED PLAIN TEXT to
    <repo>/data/corpus_raw/<domain>/<title>__<hash8>.txt
and append a line to
    <repo>/data/corpus_raw/manifest.jsonl
recording where it came from + its local path. Production reproduction is then just:
copy `data/corpus_raw/` over and run `scripts/reingest_from_archive.py`.

Saving the parsed text (not the original PDF/HTML) makes reproduction network-free and
parser-independent. Archiving is OFF by default and only turns on when the environment
variable NIPUN_ARCHIVE_CORPUS=1 is set — so it runs during deliberate corpus ingestion
runs and never archives private per-user uploads processed by the Celery workers.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import structlog

from src.ingestion.parser import ParsedDocument

log = structlog.get_logger("ingestion.archive")

# Repo root = backend/src/ingestion/archive.py → parents[3]. CWD-independent.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ARCHIVE_ROOT = Path(os.getenv("NIPUN_CORPUS_ARCHIVE_DIR", str(_REPO_ROOT / "data" / "corpus_raw")))
_MANIFEST = _ARCHIVE_ROOT / "manifest.jsonl"


def archive_enabled() -> bool:
    return os.getenv("NIPUN_ARCHIVE_CORPUS", "0") == "1"


def _safe(name: str, limit: int = 60) -> str:
    slug = re.sub(r"[^\w\-]+", "_", (name or "").strip())[:limit].strip("_")
    return slug or "doc"


def archive_document(doc: ParsedDocument, chunks: int = 0) -> str | None:
    """Save the parsed text + a manifest entry for one indexed document. Best-effort:
    never raises, so an archiving failure can't break ingestion."""
    if not archive_enabled():
        return None
    try:
        domain = doc.domain or "general"
        domain_dir = _ARCHIVE_ROOT / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        fpath = domain_dir / f"{_safe(doc.title)}__{doc.source_hash[:8]}.txt"
        if not fpath.exists():
            fpath.write_text(doc.text or "", encoding="utf-8")
        entry = {
            "domain": domain,
            "title": doc.title,
            "language": doc.language,
            "source_url": doc.source_url,
            "source_hash": doc.source_hash,
            "section": (doc.metadata or {}).get("section"),
            "metadata": doc.metadata or {},
            "local_path": str(fpath.relative_to(_ARCHIVE_ROOT)),
            "chars": len(doc.text or ""),
            "chunks": chunks,
        }
        with _MANIFEST.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return str(fpath)
    except Exception as exc:  # pragma: no cover - archiving is best-effort
        log.warning("archive_failed", title=(doc.title or "")[:80], error=str(exc))
        return None
