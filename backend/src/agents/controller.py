"""
Mission Controller — the orchestrator's decision brain.

Given a user prompt (and cheap signals already computed: domain, intent, complexity), the
controller decides HOW to fulfil the wish and WHICH independent agents to enlist, in what
order. It turns "here is a prompt" into an explicit, inspectable Mission the orchestrator
graph then carries out end-to-end: collect details → fetch/compile → reason → synthesize →
verify → (for tasks) prepare-and-confirm.

Design goals (in priority order): accuracy & credibility, then scale & speed. So the
decision is RULES-FIRST (zero latency for the common cases) with a fast-LLM fallback only
for the genuinely ambiguous ones, and it names capabilities from the registry rather than
hardcoding — new agents/integrations added in later phases are automatically plannable.

Modes:
  answer   — conversational / trivial; no retrieval.
  inform   — a grounded factual answer from the knowledge base (+ live data when needed).
  research — multi-part / comparison / document analysis; decompose → per-part → synthesize.
  task     — a real-world action; compile → plan → PREPARE (never auto-execute side effects).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from src.agents.capabilities import get_capability
from src.agents.planner import classify_route

log = structlog.get_logger("agents.controller")

# route (from the planner) → mission mode
_ROUTE_TO_MODE = {
    "simple_answer": "answer",
    "agentic_rag": "inform",
    "multi_hop": "research",
    "research": "research",
    "task_execution": "task",
}

# The default agent pipeline per mode, named from the capability registry. This is the
# "how to complete it" recipe — the orchestrator runs these; unknown names are skipped, so
# a phase can add a capability and slot it in without breaking older missions.
# The agent pipeline per mode. "understand" is one merged LLM call doing safety + language +
# classification; "reasoner"/"critic" are folded into the generator's prompt at zero extra
# cost (not separate calls). Only names present in the registry are surfaced, so a future
# phase can slot a new capability in without breaking older missions.
_PIPELINES = {
    "answer": ["understand", "memory"],
    "inform": ["understand", "clarifier", "memory", "retriever", "grader", "live_data",
               "reasoner", "verifier"],
    "research": ["understand", "clarifier", "planner", "query_decomposer", "retriever",
                 "grader", "live_data", "synthesizer", "verifier"],
    "task": ["understand", "clarifier", "planner", "retriever", "live_data",
             "task_assistant", "executor", "verifier"],
}


@dataclass
class Mission:
    mode: str                      # answer | inform | research | task
    route: str                     # the concrete graph route (kept for the existing graph)
    capabilities: list[str] = field(default_factory=list)
    rationale: str = ""
    method: str = "rules"

    def to_dict(self) -> dict:
        # Only surface capabilities that actually exist in the registry (extensibility-safe).
        known = [c for c in self.capabilities if get_capability(c)]
        return {
            "mode": self.mode, "route": self.route,
            "agents": known, "rationale": self.rationale,
        }


async def decide_mission(
    query: str, complexity: str = "simple", domain: str = "general",
    intent: str = "", correlation_id: str = "", route: str | None = None,
) -> Mission:
    """Decide the mission for a prompt and map it to a mode + capability pipeline. Never raises.

    Route selection is DETERMINISTIC-RULES-FIRST (unchanged, so behaviour never regresses):
    a confident keyword/complexity rule always wins. Only when the rules are inconclusive do we
    reuse the `route` the intake step already chose in its single classification call — avoiding
    a second route-classification LLM round-trip. If neither applies, we fall back to the full
    route classifier (rules + LLM)."""
    from src.agents.planner import _rule_route

    rule_route = _rule_route(query, complexity)
    if rule_route:
        route = rule_route                       # deterministic rules win (same as before)
    elif route not in _ROUTE_TO_MODE:
        route = await classify_route(query, complexity, correlation_id)
    # else: use the valid `route` the intake step already decided (saves the LLM call).
    mode = _ROUTE_TO_MODE.get(route, "inform")
    capabilities = list(_PIPELINES.get(mode, _PIPELINES["inform"]))
    rationale = {
        "answer": "Conversational or trivial — answer directly, no retrieval.",
        "inform": "Factual question — ground the answer in retrieved (and, if needed, live) evidence, then score credibility.",
        "research": "Multi-part or comparative — decompose, answer each grounded, then synthesize.",
        "task": "Actionable request — compile and plan, then prepare for your confirmation (nothing executes without it).",
    }[mode]
    mission = Mission(mode=mode, route=route, capabilities=capabilities, rationale=rationale)
    log.info("mission_decided", mode=mode, route=route, domain=domain,
             agents=len(mission.capabilities), correlation_id=correlation_id)
    return mission
