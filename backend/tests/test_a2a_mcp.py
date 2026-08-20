"""Tests for Phase 6 A2A card verification, MCP tools, and RLM bounds."""

from src.a2a.card import AgentCard, sign_card, verify_card
from src.mcp import get_tool, list_tools
from src.research.rlm import _chunk

# ── A2A Agent Card cryptographic verification ─────────────────────────────────

def test_card_verified_when_signed_and_trusted():
    card = AgentCard(agent_id="specialist-1", name="Research", capabilities=["research"])
    sig = sign_card(card, secret="s3cr3t")
    assert verify_card(card, sig, secret="s3cr3t", trusted=["specialist-1"]) == "verified"


def test_card_bad_signature():
    card = AgentCard(agent_id="specialist-1", name="Research")
    assert verify_card(card, "deadbeef", secret="s3cr3t", trusted=["specialist-1"]) == "bad_signature"


def test_card_untrusted_even_if_signed():
    # The inflated-card attack: a validly-signed card from a non-allowlisted agent is rejected.
    card = AgentCard(agent_id="rogue", name="Totally Legit", capabilities=["everything"])
    sig = sign_card(card, secret="s3cr3t")
    assert verify_card(card, sig, secret="s3cr3t", trusted=["specialist-1"]) == "untrusted"


def test_card_tamper_changes_signature():
    card = AgentCard(agent_id="specialist-1", name="Research", capabilities=["research"])
    sig = sign_card(card, secret="s3cr3t")
    # Tamper with the card AFTER signing — signature must no longer verify.
    card.capabilities.append("admin")
    assert verify_card(card, sig, secret="s3cr3t", trusted=["specialist-1"]) == "bad_signature"


def test_card_malformed():
    card = AgentCard(agent_id="", name="x")
    assert verify_card(card, "", secret="s", trusted=[]) == "malformed"


# ── MCP tools ─────────────────────────────────────────────────────────────────

def test_tools_registered():
    names = {t["name"] for t in list_tools()}
    assert {"indiankanoon", "agmarknet", "imd_weather", "digilocker"} <= names


async def test_tool_unavailable_without_key():
    result = await get_tool("indiankanoon").call({"query": "bail"})
    assert result.status == "unavailable"  # no key → degrades, never fabricates


async def test_tool_blocks_credentials_in_params():
    result = await get_tool("agmarknet").call({"note": "otp 123456", "commodity": "wheat"})
    assert result.status == "blocked"


# ── RLM bounds ────────────────────────────────────────────────────────────────

def test_rlm_chunking():
    chunks = _chunk("abcdefghij", 4)
    assert chunks == ["abcd", "efgh", "ij"]
    assert _chunk("", 4) == [""]
