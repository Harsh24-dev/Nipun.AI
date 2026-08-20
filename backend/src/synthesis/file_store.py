"""
Generated-file store — hold a generated deliverable (docx/pptx/…) so the user can download it.

Backed by Redis (base64) with a TTL and the owner's id, so a file made on ANY worker can be
downloaded from ANY worker, RBAC-checked, without a DB migration. Files are small (KB) and
ephemeral (a download link, not permanent storage). Best-effort: if Redis is down, storing
returns None and the caller degrades to showing the content inline instead of a download link.
"""

from __future__ import annotations

import base64
import uuid

import structlog

log = structlog.get_logger("synthesis.file_store")

_KEY = "nipun:genfile:{fid}"
_TTL = 60 * 60 * 24   # 24h download window


async def store_file(owner_id: str, filename: str, mime: str, data: bytes,
                     ttl: int = _TTL) -> str | None:
    """Store file bytes and return a file_id, or None if it could not be stored."""
    try:
        from src.db.redis import set_json
        fid = str(uuid.uuid4())
        await set_json(_KEY.format(fid=fid), {
            "owner_id": owner_id, "filename": filename, "mime": mime,
            "b64": base64.b64encode(data).decode("ascii"),
        }, ttl=ttl)
        log.info("genfile_stored", file_id=fid, owner_id=owner_id, filename=filename, bytes=len(data))
        return fid
    except Exception as exc:
        log.warning("genfile_store_failed", error=str(exc))
        return None


async def get_file(file_id: str) -> dict | None:
    """Return {owner_id, filename, mime, data(bytes)} or None. Caller enforces ownership."""
    try:
        from src.db.redis import get_json
        rec = await get_json(_KEY.format(fid=file_id))
        if not rec:
            return None
        return {
            "owner_id": rec.get("owner_id", ""),
            "filename": rec.get("filename", "download"),
            "mime": rec.get("mime", "application/octet-stream"),
            "data": base64.b64decode(rec.get("b64", "")),
        }
    except Exception as exc:
        log.warning("genfile_get_failed", error=str(exc))
        return None
