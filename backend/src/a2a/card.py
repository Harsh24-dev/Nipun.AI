"""
A2A Agent Cards (optional).

Specialists can be exposed as A2A servers advertising a SIGNED Agent Card at
/.well-known/agent.json. The orchestrator acts as A2A client and CRYPTOGRAPHICALLY
verifies the card signature (not just its description — the inflated-card injection
attack is real) AND checks a trusted-agent allowlist before use. Short-lived per-agent
OAuth2 M2M tokens are issued for calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC

import structlog

from src.config import settings
from src.core.metrics import A2A_CARD_VERIFICATIONS

log = structlog.get_logger("a2a.card")


@dataclass
class AgentCard:
    agent_id: str
    name: str
    version: str = "1.0"
    url: str = ""
    capabilities: list[str] = field(default_factory=list)

    def canonical(self) -> str:
        # Deterministic serialisation so the signature covers the WHOLE card.
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def sign_card(card: AgentCard, secret: str | None = None) -> str:
    secret = secret if secret is not None else settings.A2A_SIGNING_SECRET
    return hmac.new(secret.encode(), card.canonical().encode(), hashlib.sha256).hexdigest()


def verify_card(card: AgentCard, signature: str, *, secret: str | None = None,
                trusted: list[str] | None = None) -> str:
    """
    Return an outcome: verified | bad_signature | untrusted | malformed.
    Verification requires BOTH a valid signature over the full card AND the agent_id
    being on the trusted allowlist.
    """
    secret = secret if secret is not None else settings.A2A_SIGNING_SECRET
    trusted = trusted if trusted is not None else settings.A2A_TRUSTED_AGENTS

    if not card.agent_id or not signature:
        A2A_CARD_VERIFICATIONS.labels(outcome="malformed").inc()
        return "malformed"

    expected = sign_card(card, secret)
    if not hmac.compare_digest(expected, signature):
        A2A_CARD_VERIFICATIONS.labels(outcome="bad_signature").inc()
        log.warning("a2a_bad_signature", agent_id=card.agent_id)
        return "bad_signature"

    if card.agent_id not in set(trusted):
        A2A_CARD_VERIFICATIONS.labels(outcome="untrusted").inc()
        log.warning("a2a_untrusted_agent", agent_id=card.agent_id)
        return "untrusted"

    A2A_CARD_VERIFICATIONS.labels(outcome="verified").inc()
    return "verified"


def issue_m2m_token(agent_id: str, ttl: int | None = None) -> str:
    """Issue a short-lived per-agent OAuth2-style M2M token (JWT, HS256)."""
    from datetime import datetime, timedelta

    from jose import jwt

    ttl = ttl if ttl is not None else settings.A2A_TOKEN_TTL
    now = datetime.now(UTC)
    claims = {
        "sub": agent_id, "scope": "a2a", "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_m2m_token(token: str) -> dict | None:
    from jose import jwt

    try:
        claims = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if claims.get("scope") != "a2a":
            return None
        return claims
    except Exception:
        return None
