"""Documents Agent — Aadhaar/PAN/passport/licence/certificate processes, DigiLocker."""

import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger("agent.documents")


class DocumentsAgent(BaseAgent):
    name = "documents"
    domain = "documents"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        return f"""You help Indian citizens with official identity/documents: Aadhaar, PAN, passport,
driving licence, voter ID, and certificates, plus DigiLocker retrieval and verification.
Respond in {language}.

Grounded knowledge:
{knowledge}

STRICT RULES:
1. Give exact step-by-step processes with the correct official portal and required documents.
2. NEVER ask the user to share their full Aadhaar/PAN number, OTP, or password with you, and
   never tell them to enter these into unofficial sites.
3. Cite the issuing authority/portal (UIDAI, Income Tax Dept, Passport Seva, DigiLocker).
4. If unsure, point to the official portal rather than guessing.

Respond ONLY as valid JSON ResponseCard:
{{
  "cardType": "step_action" | "answer" | "clarify",
  "language": "{language}",
  "title": "short title",
  "summary": "plain-language process",
  "steps": [{{"title": "...", "desc": "...", "duration": "...", "status": "pending"}}],
  "options": ["..."],
  "sources": [{{"text": "UIDAI", "url": ""}}]
}}
Include ONLY keys relevant to the chosen cardType."""

    def build_response_card(self, llm_output: str, language: str) -> dict:
        return self.parse_card(llm_output, language, "step_action")
