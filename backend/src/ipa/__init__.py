"""
IPA — Intelligent Process Automation.

A server-side browser agent that actually EXECUTES the web tasks a user asks for (book, apply,
fill, search-and-act), instead of only planning them. The approach mirrors modern browser-use /
WebVoyager agents:

  1. plan      — an LLM turns the goal into a verifiable CHECKLIST + ONE consolidated info form.
  2. perceive  — Playwright renders the page; JS marks every interactive element with an index
                 and draws labelled boxes (the "set-of-marks" technique) + a screenshot.
  3. decide    — an LLM picks the next action (click[i] / type[i] / select / navigate / done)
                 toward the current checklist step, from the indexed elements + screenshot.
  4. act       — the action runs in the real browser.
  5. verify    — an LLM checks the result matches the step's expected outcome; retry or ask human.

Human-in-the-loop and safety are first-class: the agent HARD-STOPS at login / OTP / payment /
final-submit and hands control back, the user can pause / take over / stop at any time, and every
screenshot is streamed live so the user sees exactly what the agent is doing.
"""
