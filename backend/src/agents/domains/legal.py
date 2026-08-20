"""
Legal Domain Agent — IPC/CrPC advice, bail applications, RTI drafts, case search.
"""

import json

import structlog

from src.agents.base import BaseAgent, extract_json_object

log = structlog.get_logger("agent.legal")


class LegalAgent(BaseAgent):
    name = "legal"
    domain = "legal"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        state = profile.get("state", "India")
        occupation = profile.get("occupation", "citizen")
        name = profile.get("name", "")
        episodic = "\n".join(e.get("summary", "") for e in context.get("episodic_context", []))
        knowledge = context.get("knowledge", "No specific legal documents found.")

        return f"""You are a senior Indian legal expert with deep knowledge of IPC, CrPC, Constitution of India, Evidence Act, and state laws.

User Profile:
- Name: {name or 'Not provided'}
- State: {state}
- Language: {language}
- Occupation: {occupation}

Relevant legal knowledge (ground your answer ONLY in these — do not invent citations):
{knowledge}

Prior context from previous conversations:
{episodic or 'No prior legal context.'}

STRICT RULES:
1. Every legal claim MUST cite its source: section number + act name (e.g. "Section 438 CrPC")
2. Respond in {language} using simple words a non-lawyer can understand
3. Never give a definitive legal opinion — always recommend consulting a lawyer for final decisions
4. If the query requires a document draft (bail application, RTI, legal notice), produce the COMPLETE draft in `summary`
5. Always mention free legal aid: NALSA helpline 15100
6. Do NOT make up case law — only cite what is in the knowledge base

Respond ONLY as valid JSON matching this EXACT ResponseCard schema:
{{
  "cardType": "step_action" | "answer" | "document" | "clarify",
  "language": "{language}",
  "title": "short panel title",
  "summary": "plain language summary / full document text for cardType=document",

  // For cardType = "step_action"
  "steps": [
    {{"title": "Step title", "desc": "What to do and why", "duration": "1-2 days", "status": "pending"}}
  ],

  // For cardType = "clarify"
  "options": ["Option A", "Option B"],

  "sources": [{{"text": "Section 438 CrPC", "url": ""}}],
  "disclaimer": "यह सामान्य कानूनी जानकारी है। अपने मामले के लिए वकील से परामर्श लें।"
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
            card.setdefault("disclaimer", "यह सामान्य कानूनी जानकारी है। अपने मामले के लिए वकील से परामर्श लें।")
            # Normalise legacy fields
            if "content" in card and "summary" not in card:
                card["summary"] = card.pop("content")
            # Normalise legacy step fields: detail→desc, number removed, add status
            if card.get("steps"):
                normalised = []
                for s in card["steps"]:
                    normalised.append({
                        "title": s.get("title", ""),
                        "desc": s.get("desc") or s.get("detail") or s.get("description") or "",
                        "duration": s.get("duration") or s.get("time_required"),
                        "status": s.get("status", "pending"),
                    })
                card["steps"] = normalised
            return card
        except json.JSONDecodeError:
            log.warning("legal_card_json_parse_failed", preview=(llm_output or "")[:100])
            return {
                "cardType": "answer",
                "language": language,
                "title": "Legal Information",
                "summary": llm_output or "",
                "sources": [],
                "disclaimer": "यह सामान्य कानूनी जानकारी है। अपने मामले के लिए वकील से परामर्श लें।",
            }
