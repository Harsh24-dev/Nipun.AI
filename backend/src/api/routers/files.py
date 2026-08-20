"""
Download generated files (deliverables the assistant produced: pptx, docx, …).

RBAC: a file can only be downloaded by the user who owns it. Files are ephemeral (held in
the shared store with a TTL); a 404 means it expired or never existed.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.api.deps import get_current_user
from src.synthesis.file_store import get_file

log = structlog.get_logger("api.files")
router = APIRouter()


@router.get("/files/{file_id}", summary="Download a generated file (owner only)", tags=["files"])
async def download_file(file_id: str, user: dict = Depends(get_current_user)) -> Response:
    rec = await get_file(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="File not found or expired.")
    if rec["owner_id"] and rec["owner_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="File not found.")  # don't reveal existence
    filename = rec["filename"] or "download"
    return Response(
        content=rec["data"],
        media_type=rec["mime"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
