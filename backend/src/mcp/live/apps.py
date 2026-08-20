"""
Google app integrations — Gmail & Drive (read-only, consent-gated).

These act on the USER's own data, so they require the user's consented OAuth session
(an access token obtained via Google's OAuth flow), never raw credentials. Until the
OAuth flow is wired (GOOGLE_APPS_ENABLED + client config + a per-user token), the tools
report they need consent. When a consented `access_token` is supplied, they perform
read-only calls (list/read) — writing/sending stays behind PREPARE→CONFIRM→EXECUTE.
"""

from __future__ import annotations

import asyncio

import structlog

from src.config import settings
from src.mcp.base import MCPTool, ToolResult
from src.mcp.live.http import get_json

log = structlog.get_logger("mcp.live.apps")


def _consent_needed(tool: str) -> ToolResult:
    return ToolResult(
        tool, "unavailable",
        text=("This needs your consent. Connect your Google account (read-only OAuth) to let "
              "Nipun read this for you. Nipun never asks for your password or OTP, and never "
              "sends or changes anything without your explicit confirmation."),
        data={"requires": "google_oauth_consent"},
    )


class GmailTool(MCPTool):
    name = "gmail"
    description = "Read the user's Gmail messages (consented, read-only)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        token = params.get("access_token")
        if not (settings.GOOGLE_APPS_ENABLED and settings.GOOGLE_OAUTH_CLIENT_ID and token):
            log.info("gmail_consent_needed")
            return _consent_needed(self.name)
        query = params.get("query", "")
        log.info("gmail_call", has_query=bool(query))
        listing = await get_json(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"q": query, "maxResults": settings.LIVE_MAX_RESULTS},
            headers={"Authorization": f"Bearer {token}"},
        )
        msgs = ((listing or {}).get("messages") or [])[: settings.LIVE_MAX_RESULTS]
        # Fetch per-message metadata concurrently instead of one blocking round-trip at a time.
        fulls = await asyncio.gather(
            *[
                get_json(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}",
                    params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                    headers={"Authorization": f"Bearer {token}"},
                )
                for m in msgs
            ],
            return_exceptions=True,
        )
        results = []
        for m, full in zip(msgs, fulls):
            if isinstance(full, Exception):
                log.debug("gmail_message_fetch_failed", msg_id=m.get("id"), error=str(full))
                full = None
            headers = {h["name"]: h["value"] for h in (((full or {}).get("payload") or {}).get("headers") or [])}
            results.append({
                "title": headers.get("Subject", "(no subject)"),
                "url": f"https://mail.google.com/mail/u/0/#inbox/{m['id']}",
                "content": f"From {headers.get('From','')} on {headers.get('Date','')}: "
                           f"{(full or {}).get('snippet','')}",
                "source": "Gmail",
            })
        if not results:
            return ToolResult(self.name, "ok", data={"results": []}, text="No matching emails found.")
        return ToolResult(self.name, "ok", data={"results": results},
                          text=" | ".join(r["title"] for r in results))


class DriveTool(MCPTool):
    name = "google_drive"
    description = "Search/read the user's Google Drive files (consented, read-only)."
    read_only = True

    async def _call(self, params: dict) -> ToolResult:
        token = params.get("access_token")
        if not (settings.GOOGLE_APPS_ENABLED and settings.GOOGLE_OAUTH_CLIENT_ID and token):
            log.info("drive_consent_needed")
            return _consent_needed(self.name)
        query = params.get("query", "")
        log.info("drive_call", has_query=bool(query))
        data = await get_json(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": f"name contains '{query}'" if query else "",
                    "pageSize": settings.LIVE_MAX_RESULTS,
                    "fields": "files(id,name,mimeType,webViewLink,modifiedTime)"},
            headers={"Authorization": f"Bearer {token}"},
        )
        files = (data or {}).get("files") or []
        if not files:
            return ToolResult(self.name, "ok", data={"results": []}, text="No matching Drive files.")
        results = [{"title": f.get("name", ""), "url": f.get("webViewLink", ""),
                    "content": f"{f.get('name','')} ({f.get('mimeType','')}), modified {f.get('modifiedTime','')}",
                    "source": "Google Drive"} for f in files]
        return ToolResult(self.name, "ok", data={"results": results},
                          text=" | ".join(r["title"] for r in results))
