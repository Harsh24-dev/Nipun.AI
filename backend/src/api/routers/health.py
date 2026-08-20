import asyncio
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.core.logging import get_logger

log = get_logger("api.health")

router = APIRouter()

# Per-dependency timeout so one hung backend (Redis/Postgres/Qdrant) cannot hang the
# health handler indefinitely.
_DEP_TIMEOUT_SECONDS = 2.0


class ServiceCheck(BaseModel):
    status: str = Field(..., description="'ok' when reachable, 'down' when the dependency failed")
    latency_ms: float | None = Field(None, description="Round-trip latency in milliseconds")
    error: str | None = Field(None, description="Error message when status is 'down'")


class HealthResponse(BaseModel):
    status: str = Field(..., description="'ok' when all dependencies are healthy, 'degraded' when one or more are down")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Deployed application version")
    checks: dict[str, ServiceCheck] = Field(..., description="Per-dependency health details (postgres, redis, qdrant)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "ok",
                    "service": "nipun-ai-gateway",
                    "version": "0.1.0",
                    "checks": {
                        "postgres": {"status": "ok", "latency_ms": 2.31, "error": None},
                        "redis": {"status": "ok", "latency_ms": 0.85, "error": None},
                        "qdrant": {"status": "ok", "latency_ms": 3.12, "error": None},
                    },
                },
                {
                    "status": "degraded",
                    "service": "nipun-ai-gateway",
                    "version": "0.1.0",
                    "checks": {
                        "postgres": {"status": "ok", "latency_ms": 2.31, "error": None},
                        "redis": {"status": "down", "latency_ms": None, "error": "Connection refused"},
                        "qdrant": {"status": "ok", "latency_ms": 3.12, "error": None},
                    },
                },
            ]
        }
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"description": "All dependencies healthy"},
        207: {"description": "One or more dependencies are degraded", "model": HealthResponse},
    },
    summary="Service health check",
    description=(
        "Returns liveness status and per-dependency latency for Postgres, Redis, and Qdrant. "
        "Returns **200** when everything is healthy and **207** when one or more dependencies are down."
    ),
)
async def health_check() -> HealthResponse:
    from fastapi.responses import JSONResponse

    log.info("health_check_requested", endpoint="/health")
    checks, overall = await _run_dependency_checks()
    body = HealthResponse(
        status=overall,
        service="nipun-ai-gateway",
        version="0.1.0",
        checks=checks,
    )
    status_code = 200 if overall == "ok" else 207
    log.info("health_checked", overall=overall, status_code=status_code,
             **{name: c.status for name, c in checks.items()})
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def _check(name: str, probe) -> ServiceCheck:
    """Run one dependency probe under a hard timeout; classify timeout/error as 'down'."""
    start = time.perf_counter()
    try:
        await asyncio.wait_for(probe(), timeout=_DEP_TIMEOUT_SECONDS)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        log.debug("dependency_probe_ok", dependency=name, latency_ms=latency_ms)
        return ServiceCheck(status="ok", latency_ms=latency_ms)
    except asyncio.TimeoutError:
        log.warning("dependency_probe_timeout", dependency=name,
                    timeout_seconds=_DEP_TIMEOUT_SECONDS)
        return ServiceCheck(status="down", error=f"timeout after {_DEP_TIMEOUT_SECONDS}s")
    except Exception as exc:
        log.warning("dependency_probe_failed", dependency=name,
                    error=str(exc), error_type=type(exc).__name__)
        return ServiceCheck(status="down", error=str(exc))


async def _run_dependency_checks() -> tuple[dict[str, ServiceCheck], str]:
    """Probe Postgres, Redis, and Qdrant (each timeout-bounded). Returns per-dep results and
    an overall status ('ok' / 'degraded')."""
    async def _pg() -> None:
        from src.db.postgres import fetchval
        await fetchval("SELECT 1")

    async def _redis() -> None:
        from src.db.redis import get_redis
        await get_redis().ping()

    async def _qdrant() -> None:
        from src.db.qdrant import get_qdrant
        await get_qdrant().get_collections()

    log.debug("dependency_checks_started")
    checks: dict[str, ServiceCheck] = {
        "postgres": await _check("postgres", _pg),
        "redis": await _check("redis", _redis),
        "qdrant": await _check("qdrant", _qdrant),
    }
    overall = "ok" if all(c.status == "ok" for c in checks.values()) else "degraded"
    if overall != "ok":
        log.warning("dependency_checks_degraded",
                    down=[name for name, c in checks.items() if c.status != "ok"])
    return checks, overall


@router.get(
    "/livez",
    summary="Liveness probe",
    description="Returns 200 whenever the process is up. Performs NO dependency checks — used "
                "by orchestrators to decide whether to restart the container.",
)
async def livez() -> dict:
    log.debug("liveness_probed", endpoint="/livez")
    return {"status": "alive"}


@router.get(
    "/readyz",
    responses={
        200: {"description": "All dependencies healthy — ready to serve traffic"},
        503: {"description": "One or more dependencies are degraded/down — not ready"},
    },
    summary="Readiness probe",
    description="Checks all dependencies (timeout-bounded) and returns 503 when any is "
                "degraded/down, so a load balancer can route traffic away until it recovers.",
)
async def readyz():
    from fastapi.responses import JSONResponse

    log.info("readiness_requested", endpoint="/readyz")
    checks, overall = await _run_dependency_checks()
    body = HealthResponse(
        status=overall,
        service="nipun-ai-gateway",
        version="0.1.0",
        checks=checks,
    )
    status_code = 200 if overall == "ok" else 503
    log.info("readiness_checked", overall=overall, status_code=status_code,
             **{name: c.status for name, c in checks.items()})
    return JSONResponse(status_code=status_code, content=body.model_dump())
