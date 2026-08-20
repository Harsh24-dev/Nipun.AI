"""Government Scheme Agent — matches user profile to central/state govt schemes."""

import json

import structlog

from src.agents.base import BaseAgent, extract_json_object

log = structlog.get_logger("agent.scheme")


class SchemeAgent(BaseAgent):
    name = "scheme"
    domain = "scheme"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        return f"""You are a government scheme expert helping Indian citizens discover and apply for central and state government schemes.

User profile: {json.dumps(profile)}
Relevant schemes from database: {knowledge}

Find ALL schemes the user is eligible for based on their profile (state, occupation, income, age, gender).
Always mention PM-KISAN for farmers, Ayushman Bharat for health, PM Awas Yojana for housing if applicable.

Respond ONLY as valid JSON matching this EXACT ResponseCard schema:
{{
  "cardType": "scheme_list",
  "language": "{language}",
  "title": "Eligible Government Schemes",
  "summary": "brief overview in {language}",
  "schemes": [
    {{
      "name": "PM-KISAN",
      "eligible": true,
      "benefit": "₹6,000/year direct transfer",
      "criteria": "Small/marginal farmer with less than 2 hectares",
      "link": "pmkisan.gov.in"
    }}
  ],
  "sources": [{{"text": "MyScheme portal", "url": "myscheme.gov.in"}}]
}}"""

    def build_response_card(self, llm_output: str, language: str) -> dict:
        content = extract_json_object(llm_output)
        try:
            card = json.loads(content, strict=False)
            if not isinstance(card, dict):
                raise json.JSONDecodeError("not an object", content, 0)
            card.setdefault("language", language)
            card.setdefault("cardType", "scheme_list")
            if "content" in card and "summary" not in card:
                card["summary"] = card.pop("content")
            # Normalise scheme fields
            if card.get("schemes"):
                for s in card["schemes"]:
                    if "eligibility" in s and "criteria" not in s:
                        s["criteria"] = s.pop("eligibility")
                    if "apply_url" in s and "link" not in s:
                        s["link"] = s.pop("apply_url")
            return card
        except json.JSONDecodeError:
            log.warning("scheme_card_json_parse_failed", preview=(llm_output or "")[:100])
            return {"cardType": "scheme_list", "language": language, "title": "Government Schemes", "summary": llm_output or ""}
