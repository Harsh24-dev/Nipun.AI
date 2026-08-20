"""
Agent capability registry — the single, pluggable catalogue of every agent the
orchestrator can call.

Each agent is an INDEPENDENT unit described by a uniform `Capability`: a name, the kind of
work it does, a one-line purpose the controller reasons over, whether it has side effects
(so writes always route through PREPARE→CONFIRM), and an optional callable entry point.

Why a registry: it makes the system EXTENSIBLE by phases. A future integration — a payment
gateway, a shopping portal, a new domain expert — becomes available to the orchestrator by
registering a Capability here (and, for real actions, an ACTION_HANDLER in the executor).
No core code changes. Domain experts and task assistants are auto-registered from their own
registries, so the catalogue always reflects what actually exists at runtime — never a stale
hand-maintained list.

This is the contract the Mission Controller (agents/controller.py) plans against.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("agents.capabilities")

# Kinds of agent in the mesh. Adding a new kind is allowed — this is documentation, not a
# hard enum, so future phases aren't blocked.
KINDS = (
    "classifier",      # understand the query (domain/intent/complexity)
    "clarifier",       # collect missing details by asking
    "planner",         # decide route + decompose + build/score plans
    "retriever",       # fetch grounding documents (static corpus + user docs)
    "grader",          # judge retrieved evidence relevance/sufficiency
    "live_tool",       # fetch live external data (weather, prices, law, news)
    "reasoner",        # deliberate: plan-driven approach + self-reflection
    "domain_expert",   # compose the domain-specific answer
    "synthesizer",     # merge multi-part / multi-source answers
    "verifier",        # credibility: claim grounding, corroboration, scoring
    "memory",          # learn + recall durable facts about the user
    "task_assistant",  # compile/plan a real-world task (read-only preview)
    "executor",        # PREPARE→CONFIRM→EXECUTE side-effecting actions (gated)
)


@dataclass
class Capability:
    name: str
    kind: str
    purpose: str
    side_effecting: bool = False          # True → must go through PREPARE→CONFIRM
    domains: tuple[str, ...] = ()          # domain hints for selection ("" = any)
    run: Callable[..., Awaitable[Any]] | Callable[..., Any] | None = None
    meta: dict = field(default_factory=dict)

    def describe(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "purpose": self.purpose,
            "side_effecting": self.side_effecting,
            "domains": list(self.domains), **({"meta": self.meta} if self.meta else {}),
        }


CAPABILITIES: dict[str, Capability] = {}


def register(cap: Capability) -> Capability:
    """Register (or replace) a capability. Future integrations call this to plug in."""
    if cap.kind not in KINDS:
        log.debug("capability_novel_kind", name=cap.name, kind=cap.kind)
    CAPABILITIES[cap.name] = cap
    return cap


def get_capability(name: str) -> Capability | None:
    return CAPABILITIES.get(name)


def list_capabilities(kind: str | None = None, domain: str | None = None) -> list[Capability]:
    caps = list(CAPABILITIES.values())
    if kind:
        caps = [c for c in caps if c.kind == kind]
    if domain:
        caps = [c for c in caps if not c.domains or domain in c.domains]
    return caps


def manifest() -> list[dict]:
    """A stable, serialisable catalogue of all agents — for the controller and the API."""
    bootstrap()   # ensure any deferred groups are registered before we advertise the catalogue
    return [c.describe() for c in sorted(CAPABILITIES.values(), key=lambda c: (c.kind, c.name))]


# ── Static capability descriptors (the fixed pipeline agents) ─────────────────────
# These document the always-present agents. Their `run` points at the real entry points
# where a clean single-call adapter exists; complex multi-node agents (retriever, domain
# generator) are described here and driven by the orchestrator graph.

def _register_core() -> None:
    from src.agents.clarify import plan_clarification
    from src.agents.grading import grade_documents, rewrite_query
    from src.agents.planner import classify_route, decompose_query, generate_plans, synthesize
    from src.agents.reasoning import critique_answer, reflect_and_improve
    from src.memory.user_memory import recall_memories

    core = [
        # ONE merged intake step: deterministic crisis-rule safety floor + deterministic
        # language resolution + a single LLM call for safety-refine + domain/intent/
        # complexity/entities. Replaces three separate calls.
        Capability("understand", "classifier",
                   "Intake in one call: safety screen (with a deterministic crisis-rule "
                   "floor), response-language resolution, and domain/intent/complexity/"
                   "entity classification.", meta={"merges": ["safety", "language", "classifier"]}),
        # The output-side safety gate (disclaimers / abstain) — deterministic, no LLM call.
        Capability("safety_gate", "verifier",
                   "Gate the final answer: attach disclaimers and abstain when unsafe or "
                   "unsupported. Deterministic — no LLM call.", meta={"stage": "output"}),
        Capability("clarifier", "clarifier",
                   "Ask only for the details a good answer needs; never re-ask known facts.",
                   run=plan_clarification),
        Capability("planner", "planner",
                   "Choose the route, decompose multi-part queries, and build/score plans.",
                   run=classify_route, meta={"decompose": True, "plan": True}),
        Capability("query_decomposer", "planner",
                   "Split a multi-part question into independent sub-questions.",
                   run=decompose_query),
        Capability("retriever", "retriever",
                   "Hybrid-retrieve grounding chunks from the corpus and the user's own docs."),
        Capability("grader", "grader",
                   "Keep only evidence relevant to the query and judge sufficiency.",
                   run=grade_documents),
        Capability("query_rewriter", "grader",
                   "Reformulate the search query when retrieval was insufficient.",
                   run=rewrite_query),
        Capability("live_data", "live_tool",
                   "Fetch current external data (weather, mandi prices, law, news) with citations."),
        Capability("reasoner", "reasoner",
                   "Follow the plan and self-critique the draft for completeness and correctness.",
                   run=reflect_and_improve),
        Capability("critic", "verifier",
                   "Final adversarial accuracy-and-safety review for high-stakes domains "
                   "(health/legal/finance) before delivery.",
                   run=critique_answer, domains=("health", "legal", "finance")),
        Capability("synthesizer", "synthesizer",
                   "Merge grounded sub-answers into one coherent, non-redundant answer.",
                   run=synthesize),
        Capability("verifier", "verifier",
                   "Score credibility: claim grounding, cross-source corroboration, calibrated trust."),
        Capability("memory", "memory",
                   "Learn durable facts about the user and recall the relevant ones each turn.",
                   run=recall_memories),
    ]
    for c in core:
        register(c)


def _register_domain_experts() -> None:
    """Auto-register every domain agent from the live registry as an independent expert."""
    from src.agents.registry import REGISTRY

    for domain, agent in REGISTRY.items():
        register(Capability(
            name=f"expert:{domain}", kind="domain_expert",
            purpose=f"Compose grounded, domain-specific answers for {domain}.",
            domains=(domain,), meta={"agent": getattr(agent, "name", domain)},
        ))


def _register_task_assistants() -> None:
    """Auto-register every read-only task assistant + the gated executor."""
    from src.tasks.assistants import _ASSISTANTS, select_assistant

    # Role-level entry: routes a task to the right specialist assistant and compiles it.
    register(Capability(
        "task_assistant", "task_assistant",
        "Compile a real-world task into a concrete, confirmable plan (routes to the right "
        "specialist assistant: bill payment, itinerary, deals, ITR draft, generic plan).",
        run=lambda domain, intent, query, params=None: select_assistant(domain, intent, query).run(params or {}),
    ))
    for name, assistant in _ASSISTANTS.items():
        register(Capability(
            name=f"task:{name}", kind="task_assistant",
            purpose=assistant.description or f"Compile a preview for {name}.",
            run=assistant.run,
        ))
    register(Capability(
        "executor", "executor",
        "PREPARE→CONFIRM→EXECUTE real-world actions (payments, bookings) — gated, "
        "human-confirmed, audited. Real handlers are added per integration in later phases.",
        side_effecting=True,
    ))


# Track which groups have registered so bootstrap() is re-entrant: a group that fails
# (e.g. an optional dep missing at import time) is retried on the next call, once the
# runtime is fully set up. This keeps `import capabilities` cheap and crash-proof while
# guaranteeing the catalogue is complete by the time an agent actually runs.
_DONE: dict[str, bool] = {"core": False, "experts": False, "tasks": False}
_GROUPS = {"core": _register_core, "experts": _register_domain_experts, "tasks": _register_task_assistants}


def bootstrap() -> None:
    """Populate the registry. Idempotent + resilient: safe to call anywhere, any number of
    times; only groups that haven't yet registered are (re)attempted."""
    for name, fn in _GROUPS.items():
        if _DONE[name]:
            continue
        try:
            fn()
            _DONE[name] = True
        except Exception as exc:      # optional dep not importable yet — retry next call
            log.debug("capability_group_deferred", group=name, error=str(exc))
    if all(_DONE.values()):
        log.info("capabilities_bootstrapped", count=len(CAPABILITIES))


# Best-effort populate on import; anything deferred is retried on first real use.
bootstrap()
