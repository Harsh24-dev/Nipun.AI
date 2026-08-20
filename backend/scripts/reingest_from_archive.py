"""
Re-ingest a corpus archive produced by `src.ingestion.archive` into Qdrant + ES.

Use this to reproduce, in another environment (e.g. production), the exact corpus that
was ingested locally — without any network fetches or original PDFs. It reads
`data/corpus_raw/manifest.jsonl`, loads each saved text file as inline content, and runs
it through the normal ingestion pipeline.

    uv run python -m scripts.reingest_from_archive
    uv run python -m scripts.reingest_from_archive --dir data/corpus_raw
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import structlog

from src.core.logging import setup_logging
from src.ingestion.pipeline import ingest_spec
from src.ingestion.sources.base import IngestSpec

log = structlog.get_logger("reingest")


async def _run(archive_dir: Path) -> None:
    from src.db.postgres import close_postgres, init_postgres
    from src.db.qdrant import init_qdrant

    manifest = archive_dir / "manifest.jsonl"
    if not manifest.exists():
        raise SystemExit(f"manifest not found: {manifest}")

    # Dedup manifest lines by source_hash (a re-run may append duplicates).
    seen: set[str] = set()
    entries: list[dict] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        h = e.get("source_hash") or e.get("local_path")
        if h in seen:
            continue
        seen.add(h)
        entries.append(e)

    await init_postgres()
    await init_qdrant()
    indexed = skipped = failed = chunks = 0
    try:
        for e in entries:
            fpath = archive_dir / e["local_path"]
            if not fpath.exists():
                failed += 1
                log.warning("archive_file_missing", path=str(fpath))
                continue
            spec = IngestSpec(
                domain=e.get("domain", "general"),
                language=e.get("language", "en"),
                title=e.get("title", fpath.stem),
                text=fpath.read_text(encoding="utf-8"),
                source_url=e.get("source_url", ""),
                section=e.get("section"),
                metadata=e.get("metadata") or {},
            )
            try:
                r = await ingest_spec(spec)
                if r["status"] == "success":
                    indexed += 1
                    chunks += r.get("chunks", 0)
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                log.error("reingest_failed", title=spec.title, error=str(exc))
    finally:
        await close_postgres()

    print(f"\nRe-ingest complete: indexed={indexed} skipped={skipped} "
          f"failed={failed} chunks={chunks} (from {len(entries)} manifest entries)\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-ingest a corpus archive")
    ap.add_argument("--dir", default="data/corpus_raw", help="archive directory")
    args = ap.parse_args()
    setup_logging()
    asyncio.run(_run(Path(args.dir)))


if __name__ == "__main__":
    main()
