import asyncio

import redis.asyncio as aioredis
import structlog

from src.config import settings

log = structlog.get_logger("db.redis")

_client: aioredis.Redis | None = None
# The loop the client's connection pool was created on. redis.asyncio connections are bound to
# their creating loop; a call from another loop (the IPA agent's Proactor thread) raises
# "got Future attached to a different loop". We marshal foreign-loop calls back to the owner
# loop via _dispatch, so persist_session / idempotency writes from the agent thread work.
_client_loop: asyncio.AbstractEventLoop | None = None


async def _dispatch(coro):
    """Await `coro` on the loop that owns the redis client (see postgres._dispatch)."""
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if _client_loop is not None and current is not _client_loop and _client_loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(coro, _client_loop)
        return await asyncio.wrap_future(fut)
    return await coro


async def init_redis() -> None:
    global _client, _client_loop
    safe_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    log.debug(f"Connecting to Redis  url={safe_url}  max_connections={settings.REDIS_MAX_CONNECTIONS}")
    _client = aioredis.from_url(
        settings.redis_url,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
        encoding="utf-8",
        # Bounded timeouts + periodic health check so a hung/slow Redis can never block a
        # request indefinitely (it surfaces as an exception the hot-path fails open on).
        socket_timeout=2,
        socket_connect_timeout=2,
        health_check_interval=30,
        retry_on_timeout=True,
    )
    await _client.ping()
    _client_loop = asyncio.get_running_loop()
    log.info(f"Redis connected and ping OK  host={settings.REDIS_HOST}  port={settings.REDIS_PORT}  db={settings.REDIS_DB}  max_connections={settings.REDIS_MAX_CONNECTIONS}")


async def close_redis() -> None:
    global _client, _client_loop
    if _client:
        await _client.aclose()
        _client = None
        _client_loop = None


def get_redis() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return _client


async def get_json(key: str) -> dict | None:
    import orjson
    value = await _dispatch(get_redis().get(key))
    if value is None:
        return None
    return orjson.loads(value)


async def set_json(key: str, data: dict, ttl: int | None = None) -> None:
    import orjson
    value = orjson.dumps(data)
    if ttl:
        await _dispatch(get_redis().setex(key, ttl, value))
    else:
        await _dispatch(get_redis().set(key, value))


async def delete(key: str) -> None:
    await _dispatch(get_redis().delete(key))


async def exists(key: str) -> bool:
    return bool(await _dispatch(get_redis().exists(key)))


async def _incr_with_expiry(key: str, ttl_seconds: int) -> int:
    pipe = get_redis().pipeline()
    await pipe.incr(key)
    await pipe.expire(key, ttl_seconds)
    results = await pipe.execute()
    return results[0]


async def incr_with_expiry(key: str, ttl_seconds: int) -> int:
    """Atomic increment with expiry — used for rate limiting."""
    return await _dispatch(_incr_with_expiry(key, ttl_seconds))
