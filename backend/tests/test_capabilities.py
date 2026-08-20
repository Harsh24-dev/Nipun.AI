"""Agent mesh — capability registry, mission controller, task-assistant routing."""

import pytest

from src.agents.capabilities import (
    Capability,
    CAPABILITIES,
    bootstrap,
    get_capability,
    list_capabilities,
    manifest,
    register,
)
from src.agents.controller import decide_mission
from src.tasks.assistants import select_assistant


def test_registry_is_populated_with_core_and_tasks():
    bootstrap()
    names = set(CAPABILITIES)
    # Core agents (understand merges safety+language+classify) + gated executor present…
    assert {"understand", "safety_gate", "clarifier", "planner", "retriever", "grader",
            "reasoner", "verifier", "memory", "task_assistant", "executor"} <= names
    # …and read-only task assistants are auto-registered.
    assert any(n.startswith("task:") for n in names)


def test_critic_capability_is_scoped_to_high_stakes_domains():
    cap = get_capability("critic")
    assert cap is not None and set(cap.domains) == {"health", "legal", "finance"}


def test_domain_experts_register_when_llm_stack_available():
    # Domain experts pull in the LLM stack; register them only where that's importable
    # (production always is — the local test venv may not be).
    pytest.importorskip("litellm")
    bootstrap()
    names = set(CAPABILITIES)
    assert "expert:farming" in names and "expert:finance" in names


def test_manifest_is_serialisable_and_sorted_by_kind():
    m = manifest()
    assert all({"name", "kind", "purpose", "side_effecting"} <= set(item) for item in m)
    kinds = [item["kind"] for item in m]
    assert kinds == sorted(kinds)


def test_executor_is_flagged_side_effecting():
    assert get_capability("executor").side_effecting is True
    # Read-only agents are not.
    assert get_capability("retriever").side_effecting is False


def test_new_capability_plugs_in_without_core_changes():
    register(Capability("payment_gateway", "executor",
                        "Charge a payment via the gateway.", side_effecting=True,
                        domains=("finance",)))
    assert get_capability("payment_gateway") is not None
    assert "payment_gateway" in {c.name for c in list_capabilities(kind="executor")}
    assert "payment_gateway" in {c.name for c in list_capabilities(domain="finance")}
    del CAPABILITIES["payment_gateway"]      # keep the shared registry clean for other tests


async def test_mission_greeting_is_answer_mode():
    m = await decide_mission("hello", "simple", "general", "greeting")
    assert m.mode == "answer" and m.route == "simple_answer"
    assert "understand" in m.capabilities


async def test_mission_action_is_task_mode():
    m = await decide_mission("book a train ticket to Delhi", "simple", "travel", "booking")
    assert m.mode == "task" and m.route == "task_execution"
    # A task mission enlists the compile + gated-executor agents.
    assert "task_assistant" in m.capabilities and "executor" in m.capabilities


async def test_mission_comparison_is_research_mode():
    m = await decide_mission("compare PPF and NPS for retirement", "simple", "finance", "compare")
    assert m.mode == "research"
    assert "synthesizer" in m.capabilities


def test_select_assistant_routes_by_task_and_falls_back():
    assert select_assistant("finance", "pay", "pay my electricity bill").name == "prepare_bill_payment"
    assert select_assistant("travel", "plan", "build an itinerary for Manali").name == "build_itinerary"
    assert select_assistant("general", "buy", "find the best deal on a phone").name == "find_deals"
    assert select_assistant("finance", "tax", "help me file my ITR").name == "assemble_itr_draft"
    # Unknown task → never a dead end.
    assert select_assistant("general", "misc", "help me organise a community event").name == "plan_task"
