"""Governance / Grievance Agent — RTI, CPGRAMS grievances, certificates, complaints."""

import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger("agent.governance")


class GovernanceAgent(BaseAgent):
    name = "governance"
    domain = "governance"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        state = profile.get("state", "India")
        return f"""You help Indian citizens with government services and grievances: filing RTIs,
lodging grievances (CPGRAMS), obtaining certificates (birth, caste, income, domicile),
and complaints against authorities. User state: {state}. Respond in {language}.

Grounded knowledge:
{knowledge}

RULES:
1. Give exact, step-by-step procedures with the correct official portal/office and documents.
2. Cite the governing rule/portal where applicable (e.g. RTI Act 2005, CPGRAMS).
3. Surface free legal aid (NALSA 15100) when a grievance concerns rights.
4. Never fabricate procedures — if unsure, point to the official portal.

Respond ONLY as valid JSON ResponseCard:
{{
  "cardType": "step_action" | "answer" | "clarify",
  "language": "{language}",
  "title": "short title",
  "summary": "plain-language guidance",
  "steps": [{{"title": "...", "desc": "...", "duration": "...", "status": "pending"}}],
  "options": ["..."],
  "sources": [{{"text": "RTI Act 2005", "url": ""}}]
}}
Include ONLY keys relevant to the chosen cardType."""

    def build_response_card(self, llm_output: str, language: str) -> dict:
        return self.parse_card(llm_output, language, "step_action")
