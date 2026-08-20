"""
Seed script: indexes core Indian legal texts.
Run once: make seed  (or: uv run python scripts/seed_legal.py)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logging import setup_logging
from src.db.postgres import init_postgres, close_postgres
from src.db.redis import init_redis, close_redis
from src.db.qdrant import init_qdrant
from src.ingestion.tasks import process_document

setup_logging()

# Core legal sources — all publicly available
LEGAL_SOURCES = [
    # IPC full text (legislative.gov.in)
    {
        "url": "https://legislative.gov.in/sites/default/files/A1860-45.pdf",
        "domain": "legal",
        "language": "en",
        "title": "Indian Penal Code 1860",
    },
    # Constitution of India
    {
        "url": "https://legislative.gov.in/sites/default/files/COI...pdf",
        "domain": "legal",
        "language": "en",
        "title": "Constitution of India",
    },
    # MyScheme API — government schemes
    {
        "url": "https://api.myscheme.gov.in/search/v4/schemes?lang=en&keyword=farmer",
        "domain": "scheme",
        "language": "en",
        "title": "Government Schemes — Farmers",
    },
]


async def seed():
    await init_postgres()
    await init_redis()
    await init_qdrant()

    print(f"Seeding {len(LEGAL_SOURCES)} legal documents...")
    for src in LEGAL_SOURCES:
        print(f"  Queuing: {src['title']}")
        # Queue as Celery task (async processing)
        process_document.delay(
            source=src["url"],
            domain=src["domain"],
            language=src["language"],
            title=src["title"],
        )

    await close_postgres()
    await close_redis()
    print("All seed jobs queued. Start the Celery worker (make worker) to process them.")


if __name__ == "__main__":
    asyncio.run(seed())
