"""Tests for the Phase 3 domain agent roster."""

from src.agents.base import BaseAgent
from src.agents.registry import REGISTRY, get_agent
from src.language.constants import SUPPORTED_DOMAINS

EXPECTED = {
    "legal", "farming", "scheme", "student", "finance", "health",
    "career", "booking", "governance", "jobs", "travel", "documents", "general",
}


def test_all_expected_agents_registered():
    assert set(REGISTRY.keys()) >= EXPECTED


def test_registered_domains_have_collections():
    # Each agent domain (except pure fallbacks) must have a Qdrant collection.
    for domain in REGISTRY:
        assert domain in SUPPORTED_DOMAINS, f"{domain} not in SUPPORTED_DOMAINS"


def test_health_is_real_agent_not_general():
    from src.agents.domains.health import HealthAgent
    assert isinstance(get_agent("health"), HealthAgent)


def test_booking_is_real_agent():
    from src.agents.domains.booking import BookingAgent
    assert isinstance(get_agent("booking"), BookingAgent)


def test_get_agent_falls_back_to_general():
    from src.agents.domains.general import GeneralAgent
    assert isinstance(get_agent("nonexistent-domain"), GeneralAgent)


def test_every_agent_builds_prompt_and_parses_card():
    for agent in REGISTRY.values():
        assert isinstance(agent, BaseAgent)
        prompt = agent.build_system_prompt({"knowledge": "K"}, {"state": "Bihar"}, "hi")
        assert isinstance(prompt, str) and len(prompt) > 50
        card = agent.build_response_card('{"cardType":"answer","title":"t","summary":"s"}', "hi")
        assert card["title"] == "t"
        # malformed output still yields a card (never raises)
        fallback = agent.build_response_card("not json", "hi")
        assert fallback["cardType"]


def test_health_agent_rules_present():
    prompt = get_agent("health").build_system_prompt({"knowledge": ""}, {}, "en")
    assert "NEVER diagnose" in prompt
    assert "licensed medical professional" in prompt


def test_booking_agent_no_execution_rule():
    prompt = get_agent("booking").build_system_prompt({"knowledge": ""}, {}, "en")
    assert "never execute" in prompt.lower() or "NEVER execute" in prompt
    assert "OTP" in prompt
