"""Student/Education Agent — NCERT help, exam prep, scholarships, career guidance."""

import json

import structlog

from src.agents.base import BaseAgent, extract_json_object

log = structlog.get_logger("agent.student")


class StudentAgent(BaseAgent):
    name = "student"
    domain = "student"

    def build_system_prompt(self, context: dict, profile: dict, language: str) -> str:
        knowledge = context.get("knowledge", "")
        return f"""You are an expert learning guide and tutor for ANYONE, at ANY level — a young
school child, a school student (any class/board), a college/university student, a competitive-
exam aspirant (JEE, NEET, UPSC, SSC, GATE, CAT, and others), a working professional re-skilling
or up-skilling, a researcher or PhD scholar, or a curious self-learner of any age. There is NO
age or level limit — pitch the depth to the learner (a child gets simple analogies; a PhD or
professional gets rigorous, technical depth).

Knowledge base: {knowledge}
Language: {language}

Help with ANY topic and goal: concept explanations at the right depth, problem solving, study
and revision plans, exam strategies, understanding research papers/articles and new findings,
learning a new skill for career growth, coding, scholarships, and general knowledge — for
studying, re-skilling, or simply understanding something better.

Respond ONLY as valid JSON matching this EXACT ResponseCard schema:
{{
  "cardType": "answer" | "step_action" | "plan" | "scheme_list" | "code_editor" | "clarify",
  "language": "{language}",
  "title": "short panel title",
  "summary": "main explanation or concept in {language}",

  // For step_action (study plan steps)
  "steps": [{{"title": "Step title", "desc": "What to study / do", "duration": "e.g. 2 hours", "status": "pending"}}],

  // For plan (study timetable)
  "plan_cols": ["Subject", "Topic", "Duration", "Resources"],
  "plan_rows": [{{"Subject": "Physics", "Topic": "Mechanics", "Duration": "2h", "Resources": "NCERT Ch 5"}}],

  // For scheme_list (scholarships)
  "schemes": [{{"name": "NSP Scholarship", "eligible": true, "benefit": "₹12,000/year", "criteria": "Income < ₹2.5 lakh", "link": "scholarships.gov.in"}}],

  // For code_editor (programming questions)
  "code": "print('Hello World')",
  "codeLanguage": "python",

  "sources": [{{"text": "NCERT Class 10 Science", "url": ""}}]
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
            log.warning("student_card_json_parse_failed", preview=(llm_output or "")[:100])
            return {"cardType": "answer", "language": language, "title": "Education Help", "summary": llm_output or ""}
