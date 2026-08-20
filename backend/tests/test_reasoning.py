"""Reasoning helpers — plan actually shapes generation; reflection is gated + safe."""

import pytest

from src.agents.reasoning import critique_answer, reasoning_directive, reflect_and_improve


def test_reasoning_directive_empty_for_no_plan():
    assert reasoning_directive(None) == ""
    assert reasoning_directive({}) == ""
    assert reasoning_directive({"steps": []}) == ""


def test_reasoning_directive_renders_plan_steps():
    plan = {"steps": [
        {"description": "Find the eligibility rules", "rationale": "needed to answer"},
        {"description": "Check the applicant against them"},
    ]}
    out = reasoning_directive(plan)
    assert "Find the eligibility rules" in out
    assert "Check the applicant against them" in out
    assert "needed to answer" in out
    # Steps are numbered guidance, not printed to the user.
    assert "1." in out and "2." in out


async def test_reflect_skips_simple_complexity_without_llm():
    # Gated: simple queries never call the LLM — returns the draft unchanged.
    text, changed = await reflect_and_improve(
        query="hi", draft_text="Hello!", knowledge_text="",
        language="en", complexity="simple",
    )
    assert changed is False and text == "Hello!"


async def test_reflect_skips_trivially_short_drafts():
    text, changed = await reflect_and_improve(
        query="explain X", draft_text="short", knowledge_text="",
        language="en", complexity="multi_step",
    )
    assert changed is False and text == "short"


async def test_critic_skips_low_stakes_domains_without_llm():
    # Gated: only high-stakes domains are critiqued — general never calls the LLM.
    long_draft = "This is a sufficiently long draft answer that would otherwise be reviewed."
    text, changed = await critique_answer(
        query="q", draft_text=long_draft, knowledge_text="",
        language="en", domain="general",
    )
    assert changed is False and text == long_draft


async def test_critic_skips_trivially_short_high_stakes_drafts():
    text, changed = await critique_answer(
        query="is this medicine safe", draft_text="Yes.", knowledge_text="",
        language="en", domain="health",
    )
    assert changed is False and text == "Yes."
