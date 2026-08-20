"""
Role-based access control (RBAC).

Two enforcement primitives used across the API:
  * ROLE checks   — `require_roles("admin", ...)` for endpoints gated to a role.
  * OWNERSHIP checks — `assert_owner(resource_owner_id, user)` so a user can only
    touch their OWN resources (documents, sessions, feedback, …).

Roles are hierarchical: admin ⊇ moderator ⊇ user. The role is read once from
Postgres and cached on the request's user dict to avoid repeated lookups.

RBAC for user-uploaded documents is additionally enforced at the VECTOR layer: every
user-doc search is filtered by owner_id (see db/qdrant.search_user_document), so even a
bug in an endpoint cannot leak another user's chunks.
"""

from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException

from src.api.deps import get_current_user
from src.db.postgres import fetchval

log = structlog.get_logger("api.rbac")

# Higher number = more privilege. admin inherits everything below it.
ROLE_LEVEL: dict[str, int] = {"user": 10, "moderator": 20, "admin": 30}
DEFAULT_ROLE = "user"


async def load_role(user: dict) -> str:
    """Resolve the caller's role (cached on the user dict for the request)."""
    if user.get("role"):
        return user["role"]
    role = await fetchval("SELECT role FROM users WHERE id = $1::uuid", user["user_id"])
    role = role or DEFAULT_ROLE
    user["role"] = role
    return role


def _has_role(role: str, required: str) -> bool:
    return ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL.get(required, 99)


def require_roles(*required: str):
    """Dependency factory: allow the request only if the caller has ANY of `required`
    (or a higher role in the hierarchy). Usage: `Depends(require_roles("admin"))`."""
    required_set = required or ("user",)

    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        role = await load_role(user)
        if any(_has_role(role, r) for r in required_set):
            return {**user, "role": role}
        log.warning("rbac_denied", user_id=user["user_id"], role=role, required=required_set)
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN",
                    "message": f"Requires role: {' or '.join(required_set)}."},
        )

    return _dep


def assert_owner(resource_owner_id: str | None, user: dict, *, resource: str = "resource") -> None:
    """Raise 404 unless the caller owns the resource (admins may pass). 404 (not 403)
    avoids leaking whether another user's resource id exists."""
    if resource_owner_id and str(resource_owner_id) == str(user["user_id"]):
        return
    if user.get("role") == "admin":
        return
    log.warning("ownership_denied", user_id=user["user_id"], resource=resource)
    raise HTTPException(status_code=404, detail=f"{resource.capitalize()} not found.")
