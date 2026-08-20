"""Tests for the dynamic planner (Phase 2) — rules paths, offline."""


from src.agents.planner import (
    Plan,
    PlanStep,
    _rule_decompose,
    _rule_route,
    classify_route,
    score_plan,
    select_plan,
)


def test_rule_route_greeting():
    assert _rule_route("hello", "simple") == "simple_answer"
    assert _rule_route("namaste", "simple") == "simple_answer"


def test_rule_route_task_execution():
    assert _rule_route("book a train ticket to Delhi", "simple") == "task_execution"
    assert _rule_route("anything", "action") == "task_execution"


def test_rule_route_multi_hop():
    assert _rule_route("compare PPF and NPS for retirement", "simple") == "multi_hop"
    assert _rule_route("What is PM-KISAN? Who is eligible? How to apply?", "simple") == "multi_hop"


def test_rule_route_returns_none_for_plain():
    assert _rule_route("what is section 302 IPC", "simple") is None


def test_score_and_select_plan_prefers_fewer_steps():
    a = Plan("agentic_rag", [PlanStep("x")], reliability=0.9, est_cost=1.0)
    b = Plan("agentic_rag", [PlanStep("x"), PlanStep("y"), PlanStep("z")], reliability=0.9, est_cost=2.0)
    assert score_plan(a) > score_plan(b)
    assert select_plan([a, b]) is a


def test_select_plan_empty():
    assert select_plan([]) is None


def test_rule_decompose_comparison():
    subs = _rule_decompose("compare PPF and NPS")
    assert len(subs) >= 2


async def test_classify_route_uses_rules_without_llm():
    # Rule-matching queries never call the LLM.
    assert await classify_route("hello", "simple") == "simple_answer"
    assert await classify_route("compare X and Y schemes", "simple") == "multi_hop"


def test_plan_to_dict_roundtrip():
    p = Plan("multi_hop", [PlanStep("do thing", "legal", [0], "because")], rationale="r")
    d = p.to_dict()
    assert d["route"] == "multi_hop"
    assert d["steps"][0]["agent_or_tool"] == "legal"
