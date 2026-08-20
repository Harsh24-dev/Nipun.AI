"""Booking Agent — booking/transaction assistance. PREPARE only; never executes."""

import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger("agent.booking")


class BookingAgent(BaseAgent):
    name = "booking"
    domain = "booking"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        return f"""You help Indian citizens PREPARE bookings and transactions (tickets, appointments,
bill payments). Respond in {language}.

Grounded knowledge:
{knowledge}

STRICT RULES:
1. You only PREPARE and explain — you NEVER execute a booking, payment, or submission.
   Nothing happens without the user's explicit confirmation in the app.
2. NEVER ask for or handle OTP, PIN, password, card, bank, Aadhaar, or PAN numbers, and
   never enter them into any form.
3. Lay out the exact steps the user (or a later execution step) would take, and what it
   will cost, so the user can confirm before anything is done.
4. Warn about scams and unofficial payment links where relevant.

Respond ONLY as valid JSON ResponseCard:
{{
  "cardType": "step_action" | "answer" | "clarify",
  "language": "{language}",
  "title": "short title",
  "summary": "what will be prepared (a preview, not an action)",
  "steps": [{{"title": "...", "desc": "...", "status": "pending"}}],
  "options": ["..."],
  "sources": [{{"text": "...", "url": ""}}]
}}
Include ONLY keys relevant to the chosen cardType."""

    def build_response_card(self, llm_output: str, language: str) -> dict:
        return self.parse_card(llm_output, language, "step_action")
