"""
BaseAgent — all domain agents extend this class.
Only 3 methods to implement: build_system_prompt, select_tools, build_response_card.
"""

import json
import time
from abc import ABC, abstractmethod

import structlog

from src.core.logging import trace_flow
from src.core.metrics import AGENT_CALLS, AGENT_DURATION
from src.llm.router import route_completion

log = structlog.get_logger("agent.base")


def extract_json_object(text: str) -> str:
    """Isolate the JSON object from an LLM reply, ROBUST to nested code fences.

    Strips an outer ```json / ``` fence, then slices from the first '{' to the last '}'. Crucially
    it does NOT split on ``` — the inline ```chart / ```diagram fences the model is told to put
    INSIDE the `summary` live in string values, and a naive `split("```")` truncated the JSON right
    there, breaking parsing and dumping the raw JSON blob into the answer."""
    t = (text or "").strip()
    if t.startswith("```"):
        nl = t.find("\n")
        t = t[nl + 1:] if nl != -1 else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        return t[s:e + 1].strip()
    return t.strip()


class BaseAgent(ABC):
    name: str = "base"
    domain: str = "general"

    @abstractmethod
    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        """Build the system prompt for this agent given assembled context."""
        ...

    @abstractmethod
    def build_response_card(self, llm_output: str, language: str) -> dict:
        """Parse LLM output into a typed ResponseCard dict."""
        ...

    @staticmethod
    def parse_card(llm_output: str, language: str, default_type: str = "answer") -> dict:
        """
        Shared JSON→ResponseCard parser (strips code fences, normalises legacy step
        fields, fills defaults). Domain agents can reuse this in build_response_card.
        Disclaimers are attached centrally by the gate, not here.
        """
        content = extract_json_object(llm_output)
        try:
            # strict=False tolerates literal newlines/tabs inside string values — a very common
            # way models emit a multi-line `summary` that would otherwise fail to parse.
            card = json.loads(content, strict=False)
            # A valid JSON list/scalar parses fine but is NOT a card — `.setdefault` below
            # would then raise AttributeError (uncaught). Route it into the fallback instead.
            if not isinstance(card, dict):
                raise json.JSONDecodeError("not an object", content, 0)
        except (json.JSONDecodeError, IndexError):
            log.warning("card_json_parse_failed", preview=(llm_output or "")[:100])
            return {"cardType": default_type, "language": language, "title": "Response",
                    "summary": llm_output or ""}
        card.setdefault("language", language)
        card.setdefault("cardType", default_type)
        if "content" in card and "summary" not in card:
            card["summary"] = card.pop("content")
        if card.get("steps"):
            card["steps"] = [
                {
                    "title": s.get("title", ""),
                    "desc": s.get("desc") or s.get("detail") or s.get("description") or "",
                    "duration": s.get("duration") or s.get("time_required"),
                    "status": s.get("status", "pending"),
                }
                for s in card["steps"]
            ]
        return card

    async def execute(
        self,
        query: str,
        language: str,
        context: dict,
        knowledge: list[dict],
        profile: dict,
        correlation_id: str = "",
    ) -> dict:
        start = time.perf_counter()
        AGENT_CALLS.labels(agent=self.name, domain=self.domain, status="started").inc()

        knowledge_text = "\n\n".join(
            f"[{k.get('source', 'Source')}]\n{k.get('text', '')}" for k in knowledge
        )

        system_prompt = self.build_system_prompt(
            context={"knowledge": knowledge_text, **context},
            profile=profile,
            language=language,
        )

        history = context.get("working_memory", [])
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})

        trace_flow(
            "agent_execute_start",
            correlation_id=correlation_id,
            agent=self.name,
            domain=self.domain,
            query=query,
            history_turns=len(history),
            knowledge_sources=[k.get("source") for k in knowledge],
            system_prompt=system_prompt,
        )

        try:
            result = await route_completion(
                messages=messages,
                complexity="multi_step",
                correlation_id=correlation_id,
            )

            card = self.build_response_card(result.content, language)
            card["correlation_id"] = correlation_id

            duration_ms = (time.perf_counter() - start) * 1000
            AGENT_CALLS.labels(agent=self.name, domain=self.domain, status="success").inc()
            AGENT_DURATION.labels(agent=self.name, domain=self.domain).observe(duration_ms)

            log.info(
                "agent_response_generated",
                agent=self.name,
                card_type=card.get("cardType"),
                duration_ms=round(duration_ms, 2),
                correlation_id=correlation_id,
            )
            trace_flow(
                "agent_execute_result",
                correlation_id=correlation_id,
                agent=self.name,
                domain=self.domain,
                card_type=card.get("cardType"),
                raw_output=result.content,
                response_card=card,
            )
            return card

        except Exception as exc:
            AGENT_CALLS.labels(agent=self.name, domain=self.domain, status="error").inc()
            log.error("agent_execute_failed", agent=self.name, error=str(exc), correlation_id=correlation_id)
            raise
