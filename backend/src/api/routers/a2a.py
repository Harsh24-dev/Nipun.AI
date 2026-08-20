"""
A2A well-known Agent Card (optional).

Exposes this service's SIGNED Agent Card at /.well-known/agent.json when A2A_ENABLED.
Clients must cryptographically verify the signature and check their trusted allowlist
before using it (see src/a2a/card.py).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException

from src.a2a.card import AgentCard, sign_card
from src.config import settings

log = structlog.get_logger("api.a2a")
router = APIRouter()


@router.get("/.well-known/agent.json", summary="A2A Agent Card (signed)")
async def agent_card() -> dict:
    if not settings.A2A_ENABLED:
        log.info("a2a_card_denied", reason="a2a_disabled")
        raise HTTPException(status_code=404, detail="A2A is not enabled on this instance.")
    log.info("a2a_card_served", agent_id="nipun-orchestrator")
    card = AgentCard(
        agent_id="nipun-orchestrator",
        name="Nipun.AI Orchestrator",
        version="3.0",
        url=f"http://localhost:{settings.APP_PORT}",
        capabilities=["grounded_qa", "multi_hop", "task_preview"],
    )
    return {"card": card.__dict__, "signature": sign_card(card)}
