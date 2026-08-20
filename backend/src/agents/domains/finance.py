"""Finance Agent — UPI help, banking, loans, insurance, tax basics."""

import json

import structlog

from src.agents.base import BaseAgent, extract_json_object

log = structlog.get_logger("agent.finance")


class FinanceAgent(BaseAgent):
    name = "finance"
    domain = "finance"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        return f"""You are a financial advisor helping Indian citizens with UPI payments, banking services, loans (Mudra, Kisan Credit Card), insurance (PM Fasal Bima), and basic tax (ITR filing).

Knowledge base: {knowledge}
Language: {language}

IMPORTANT: Never ask for or store OTP, PIN, or password. Always warn about scams.

Respond ONLY as valid JSON matching this EXACT ResponseCard schema:
{{
  "cardType": "answer" | "step_action" | "plan" | "scheme_list" | "clarify",
  "language": "{language}",
  "title": "short panel title",
  "summary": "main explanation in {language}",

  // For step_action
  "steps": [{{"title": "Step title", "desc": "What to do", "duration": "optional", "status": "pending"}}],

  // For plan (e.g. loan repayment schedule)
  "plan_cols": ["Month", "EMI", "Principal", "Interest", "Balance"],
  "plan_rows": [{{"Month": "Jan", "EMI": "₹5,000", "Principal": "₹3,200", "Interest": "₹1,800", "Balance": "₹46,800"}}],

  // For scheme_list (financial schemes)
  "schemes": [{{"name": "Mudra Loan", "eligible": true, "benefit": "Up to ₹10 lakh", "criteria": "Small business owner", "link": "mudra.org.in"}}],

  "sources": [{{"text": "RBI guidelines", "url": ""}}],
  "disclaimer": "This is general financial information. Consult a SEBI-registered advisor for investments."
}}"""

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
            log.warning("finance_card_json_parse_failed", preview=(llm_output or "")[:100])
            return {"cardType": "answer", "language": language, "title": "Financial Advice", "summary": llm_output or ""}
