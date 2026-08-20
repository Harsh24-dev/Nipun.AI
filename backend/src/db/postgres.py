import asyncio

import asyncpg
import structlog

from src.config import settings

log = structlog.get_logger("db.postgres")

_pool: asyncpg.Pool | None = None
# The event loop the pool was created on. asyncpg connections are BOUND to their creating
# loop, so a call made from a different loop (the IPA browser agent runs on its own Proactor
# thread + loop) corrupts the connection ("another operation is in progress" / "connection was
# closed in the middle of operation"). We record the owner loop and marshal any foreign-loop
# call back to it via run_coroutine_threadsafe — see _dispatch.
_pool_loop: asyncio.AbstractEventLoop | None = None


async def _dispatch(coro):
    """Await `coro` on the loop that owns the pool. If we're already on that loop (the normal
    request path) run it directly; if we're on a different loop (the IPA agent thread) hand it
    to the owner loop and bridge the result back so asyncpg only ever touches its own loop."""
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if _pool_loop is not None and current is not _pool_loop and _pool_loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(coro, _pool_loop)
        return await asyncio.wrap_future(fut)
    return await coro


async def init_postgres() -> None:
    global _pool, _pool_loop
    dsn = (
        f"postgresql://{settings.POSTGRES_USER}:***"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    log.debug("postgres_connecting", dsn=dsn, pool_size=settings.POSTGRES_POOL_SIZE)
    try:
        _pool = await asyncpg.create_pool(
            dsn=(
                f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
                f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
            ),
            min_size=5,
            max_size=settings.POSTGRES_POOL_SIZE,
            max_inactive_connection_lifetime=300,
            command_timeout=30,
        )
        _pool_loop = asyncio.get_running_loop()
        log.info(
            "postgres_ready",
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            db=settings.POSTGRES_DB,
            pool_size=settings.POSTGRES_POOL_SIZE,
        )
    except Exception as exc:
        log.exception("postgres_connect_failed", error=str(exc))
        raise


async def close_postgres() -> None:
    global _pool, _pool_loop
    if _pool:
        await _pool.close()
        _pool = None
        _pool_loop = None
        log.info("postgres_pool_closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialised. Call init_postgres() first.")
    return _pool


async def _execute(query: str, *args) -> str:
    async with get_pool().acquire() as conn:
        return await conn.execute(query, *args)


async def execute(query: str, *args) -> str:
    try:
        return await _dispatch(_execute(query, *args))
    except Exception as exc:
        log.error("postgres_execute_failed", error=str(exc), query_preview=query[:80])
        raise


async def _fetch(query: str, *args) -> list[asyncpg.Record]:
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def fetch(query: str, *args) -> list[asyncpg.Record]:
    try:
        return await _dispatch(_fetch(query, *args))
    except Exception as exc:
        log.error("postgres_fetch_failed", error=str(exc), query_preview=query[:80])
        raise


async def _fetchrow(query: str, *args) -> asyncpg.Record | None:
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchrow(query: str, *args) -> asyncpg.Record | None:
    try:
        return await _dispatch(_fetchrow(query, *args))
    except Exception as exc:
        log.error("postgres_fetchrow_failed", error=str(exc), query_preview=query[:80])
        raise


async def _fetchval(query: str, *args):
    async with get_pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def fetchval(query: str, *args):
    try:
        return await _dispatch(_fetchval(query, *args))
    except Exception as exc:
        log.error("postgres_fetchval_failed", error=str(exc), query_preview=query[:80])
        raise
