import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import settings
from src.db.postgres import fetchval
from src.db.redis import incr_with_expiry

log = structlog.get_logger("api.deps")

_bearer = HTTPBearer(auto_error=False)


def validate_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing sub claim")
        return {"user_id": user_id, "language": payload.get("language", settings.DEFAULT_LANGUAGE)}
    except JWTError as exc:
        log.warning("token_validation_failed", error=str(exc))
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": str(exc)})


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if credentials is None:
        # Anonymous fallback is a DEV convenience only. Only ever fire in the development
        # environment — never in production OR staging, even if DEBUG is accidentally left on —
        # otherwise every endpoint is an unauthenticated admin.
        if settings.DEBUG and settings.APP_ENV == "development":
            log.debug("auth_bypass_debug_mode")
            return {"user_id": "00000000-0000-0000-0000-000000000001", "language": "hi", "role": "admin"}
        log.warning("auth_missing_token")
        raise HTTPException(status_code=401, detail={"code": "MISSING_TOKEN"})
    return validate_token(credentials.credentials)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    role = await fetchval("SELECT role FROM users WHERE id = $1::uuid", user["user_id"])
    if role != "admin":
        log.warning("admin_access_denied", user_id=user["user_id"])
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Admin access required."})
    return {**user, "role": "admin"}


async def rate_limit_check(request: Request, user: dict = Depends(get_current_user)) -> None:
    key = f"rate:general:{user['user_id']}"
    try:
        count = await incr_with_expiry(key, ttl_seconds=60)
    except Exception as exc:
        # FAIL-OPEN: Redis down/slow must never take the whole API down. Allow the request
        # and warn (correlation context is bound on the request contextvars).
        log.warning("rate_limit_redis_error_fail_open", user_id=user["user_id"], error=str(exc))
        return
    if count > settings.RATE_LIMIT_PER_MINUTE:
        log.warning("rate_limit_exceeded", user_id=user["user_id"], count=count, limit=settings.RATE_LIMIT_PER_MINUTE)
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "Too many requests. Try again in 1 minute."},
        )
