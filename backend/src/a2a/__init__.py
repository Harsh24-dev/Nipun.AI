"""A2A (agent-to-agent) layer (optional) — signed, allowlisted specialists."""

from src.a2a.card import (
    AgentCard,
    issue_m2m_token,
    sign_card,
    verify_card,
    verify_m2m_token,
)

__all__ = ["AgentCard", "issue_m2m_token", "sign_card", "verify_card", "verify_m2m_token"]
