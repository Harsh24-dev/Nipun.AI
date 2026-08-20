"""General Agent — fallback for queries that don't fit other domains."""

import json

import structlog

from src.agents.base import BaseAgent, extract_json_object

log = structlog.get_logger("agent.general")


class GeneralAgent(BaseAgent):
    name = "general"
    domain = "general"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        return f"""You are Nipun.AI, a helpful assistant for Indian citizens.
Knowledge base: {knowledge}

Respond ONLY as valid JSON matching this EXACT ResponseCard schema:
{{
  "cardType": "answer" | "step_action" | "clarify" | "code_editor",
  "language": "{language}",
  "title": "short panel title",
  "summary": "main response in {language}",
  "steps": [{{"title": "Step title", "desc": "What to do", "duration": null, "status": "pending"}}],
  "options": ["Option A", "Option B"],
  "code": "optional code string",
  "codeLanguage": "python",
  "sources": [{{"text": "source name", "url": ""}}]
}}
Include ONLY keys relevant to the chosen cardType. Be concise and helpful."""

    def build_response_card(self, llm_output: str, language: str) -> dict:
        content = extract_json_object(llm_output)
        try:
            card = json.loads(content, strict=False)
            if not isinstance(card, dict):
                raise json.JSONDecodeError("not an object", content, 0)
            card.setdefault("language", language)
            card.setdefault("cardType", "answer")
            if "content" in card and "summary" not in card:
                card["summary"] = card.pop("content")
            if card.get("steps"):
                for s in card["steps"]:
                    if "desc" not in s:
                        s["desc"] = s.pop("detail", s.pop("description", ""))
                    s.setdefault("status", "pending")
            return card
        except json.JSONDecodeError:
            log.warning("general_card_json_parse_failed", preview=(llm_output or "")[:100])
            return {"cardType": "answer", "language": language, "title": "Response", "summary": llm_output or ""}
