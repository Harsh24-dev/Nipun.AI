"""
Farming Domain Agent — crop planning, mandi prices, MSP, weather advisory, scheme eligibility.
"""

import json

import structlog

from src.agents.base import BaseAgent, extract_json_object
from src.core.runtime_context import now_ist

log = structlog.get_logger("agent.farming")


def _current_season() -> str:
    # Use IST wall-clock, not the server's local/UTC time — otherwise Kharif/Rabi/Zaid can
    # flip a day early/late near month boundaries for an India-based user.
    month = now_ist().month
    if month in (6, 7, 8, 9):
        return "Kharif"
    if month in (10, 11, 12, 1, 2, 3):
        return "Rabi"
    return "Zaid"


class FarmingAgent(BaseAgent):
    name = "farming"
    domain = "farming"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        state = profile.get("state", "India")
        district = profile.get("district", "")
        land_size = profile.get("land_size_acres", "unknown")
        soil_type = profile.get("soil_type", "unknown")
        crops = ", ".join(profile.get("current_crops", [])) or "unknown"
        season = _current_season()
        knowledge = context.get("knowledge", "No specific agronomic data found.")
        episodic = "\n".join(e.get("summary", "") for e in context.get("episodic_context", []))

        return f"""You are an expert agricultural advisor with deep knowledge of Indian farming practices, crops, soil science, government schemes for farmers, and market prices.

Farmer Profile:
- Location: {district + ', ' if district else ''}{state}
- Land size: {land_size} acres
- Soil type: {soil_type}
- Current crops: {crops}
- Language: {language}
- Current season: {season}

Agronomic knowledge base (use these sources):
{knowledge}

Prior farming context:
{episodic or 'No prior context.'}

RULES:
1. All advice must be specific to {state} and the {season} season
2. Give quantities in units the farmer uses: bigha/acre/hectare based on region
3. Always mention government schemes the farmer may be eligible for
4. Mention nearest KVK (Krishi Vigyan Kendra) when giving technical advice
5. If asking about prices, provide MSP AND current mandi price if available
6. Respond in {language}

Respond ONLY as valid JSON matching this EXACT ResponseCard schema:
{{
  "cardType": "plan" | "answer" | "price_table" | "scheme_list" | "weather" | "clarify",
  "language": "{language}",
  "title": "short panel title",
  "summary": "plain language explanation in {language}",

  // For cardType = "plan"
  "plan_cols": ["Activity", "Month", "Input", "Cost (₹/acre)"],
  "plan_rows": [{{"Activity": "...", "Month": "...", "Input": "...", "Cost (₹/acre)": "..."}}],

  // For cardType = "price_table"
  "prices": [{{"crop": "Wheat", "price": "₹2,015/qtl", "change": "up|down|flat", "rate": "+2.3%"}}],

  // For cardType = "scheme_list"
  "schemes": [{{"name": "PM-KISAN", "eligible": true, "benefit": "₹6,000/year", "criteria": "Small/marginal farmer", "link": "pmkisan.gov.in"}}],

  // For cardType = "weather"
  "weather": {{
    "temp": "32°C",
    "condition": "Partly Cloudy",
    "forecast": [{{"day": "Mon", "temp": "31°C", "condition": "Sunny"}}],
    "alerts": ["Heavy rain expected Thursday"]
  }},

  // For cardType = "answer"
  // (summary field holds the main content)

  "sources": [{{"text": "ICAR recommendation", "url": ""}}],
  "disclaimer": "optional disclaimer"
}}
Include ONLY the keys relevant to the chosen cardType."""

    def build_response_card(self, llm_output: str, language: str) -> dict:
        content = extract_json_object(llm_output)
        try:
            card = json.loads(content, strict=False)
            if not isinstance(card, dict):
                raise json.JSONDecodeError("not an object", content, 0)
            card.setdefault("language", language)
            card.setdefault("cardType", "answer")
            # Normalise legacy `content` → `summary`
            if "content" in card and "summary" not in card:
                card["summary"] = card.pop("content")
            return card
        except json.JSONDecodeError:
            log.warning("farming_card_json_parse_failed", preview=(llm_output or "")[:100])
            return {
                "cardType": "answer",
                "language": language,
                "title": "Farming Advisory",
                "summary": llm_output or "",
                "sources": [],
            }
