"""Shared async HTTP helpers for live tools — one place for timeouts, a polite
User-Agent, and uniform error handling. Never raises to callers: returns None on
any failure so a single dead upstream never breaks the query path."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from src.config import settings

log = structlog.get_logger("mcp.live.http")

# Transient network errors worth ONE quick retry before giving up (a dropped keep-alive
# connection or a brief read stall). Non-transient failures (e.g. HTTP 4xx via
# raise_for_status) are not retried — they won't succeed on a second attempt.
_RETRYABLE_HTTP_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                          httpx.ReadError, httpx.RemoteProtocolError, httpx.PoolTimeout)

_UA = "NipunAI/1.0 (+https://nipun.ai; citizen-assistance assistant)"

# One pooled client reused across all live-tool calls, so we don't pay a fresh TCP+TLS
# handshake per request (the old code opened and closed a client every call). Timeout is
# still applied PER request below, so a per-call `timeout=` override keeps working. Created
# lazily on first use and closed on app shutdown via close_http_client().
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _client


async def close_http_client() -> None:
    """Close the pooled live-HTTP client (called on app shutdown)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def get_json(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int | None = None,
) -> Any | None:
    """GET a URL and parse JSON. Returns the decoded body, or None on any error."""
    return await _request("GET", url, params=params, headers=headers, timeout=timeout, want="json")


async def post_json(
    url: str,
    json_body: dict | None = None,
    headers: dict | None = None,
    timeout: int | None = None,
) -> Any | None:
    """POST JSON and parse the JSON response. Returns None on any error."""
    return await _request("POST", url, json_body=json_body, headers=headers, timeout=timeout, want="json")


async def get_text(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int | None = None,
) -> str | None:
    """GET a URL and return the raw text body, or None on any error."""
    return await _request("GET", url, params=params, headers=headers, timeout=timeout, want="text")


async def _request(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    timeout: int | None = None,
    want: str = "json",
) -> Any | None:
    hdrs = {"User-Agent": _UA, "Accept": "application/json, text/*;q=0.9"}
    if headers:
        hdrs.update(headers)
    to = timeout or settings.LIVE_HTTP_TIMEOUT
    # One retry on transient connect/read errors before giving up. Still never raises to callers:
    # on the final failure (or any non-transient error) we log and return None as before.
    for attempt in range(2):
        try:
            client = _get_client()
            resp = await client.request(
                method, url, params=params, json=json_body, headers=hdrs, timeout=to
            )
            resp.raise_for_status()
            if want == "json":
                return resp.json()
            return resp.text
        except _RETRYABLE_HTTP_ERRORS as exc:
            if attempt == 0:
                log.debug("live_http_retry", url=url[:120], method=method, error=str(exc))
                await asyncio.sleep(0.25)
                continue
            log.warning("live_http_failed", url=url[:120], method=method, error=str(exc))
            return None
        except Exception as exc:
            log.warning("live_http_failed", url=url[:120], method=method, error=str(exc))
            return None
    return None
