"""Run all SQL migrations in order. Called via: make migrate"""

import asyncio
from pathlib import Path

import structlog

from src.core.logging import setup_logging
from src.db.postgres import close_postgres, execute, init_postgres

setup_logging()
log = structlog.get_logger("db.migrate")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations() -> None:
    await init_postgres()

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for sql_file in sql_files:
        log.info("running_migration", file=sql_file.name)
        sql = sql_file.read_text(encoding="utf-8")
        await execute(sql)
        log.info("migration_complete", file=sql_file.name)

    await close_postgres()
    log.info("all_migrations_complete", count=len(sql_files))


if __name__ == "__main__":
    asyncio.run(run_migrations())
