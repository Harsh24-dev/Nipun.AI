"""
The browser agent loop: perceive → decide → act → verify, per checklist step.

For each automatable step the agent looks at the page (indexed elements + screenshot), an LLM
picks ONE next action, we perform it in the real browser, and stream the screenshot + narration
to the user. Sensitive steps (login / OTP / payment / final submit) are never automated — the
agent pauses and the user completes them, then hands control back.
"""

from __future__ import annotations

import asyncio
import json

from src.config import settings
from src.core import ipa_console as narrate
from src.core.logging import get_ipa_logger
from src.ipa.browser import BrowserSession
from src.ipa.schemas import AgentAction, RunStatus, StepStatus, event
from src.ipa.session import TaskSession, persist_session
from src.llm.router import route_completion

log = get_ipa_logger("ipa.agent")

_MAX_DECISIONS_PER_STEP = 7   # LLM decisions per step (each yields 1-3 batched actions)


def _record_trace(session, step, action, elements, outcome: str) -> None:
    """Record a generalized (personal-data-free) action for the reusable recipe — the typed value
    is stored as the FORM-FIELD NAME it came from, so any user can replay the steps."""
    if "failed" in outcome:
        return
    from src.ipa.recipes import value_key
    el = next((e for e in elements if e.get("index") == action.index), None)
    vk = value_key(action.text, session.answers)
    session.trace.append({
        "step": step.id, "action": action.type,
        "target": (el or {}).get("text", "")[:60], "target_tag": (el or {}).get("tag", ""),
        "value_key": vk, "value": None if vk else (action.text[:60] or None),
    })

# Deterministic safety net: even if the LLM tries, never let the agent type a secret or click the
# final money/login/submit control — those are handed to the human.
#
# TWO layers guard the HARD INVARIANT (fill-and-hand-off; never auto-submit / touch login/OTP):
#   1. `_is_final_submit` (below) — the PRIMARY, STRUCTURAL guarantee. It inspects the DOM
#      descriptor (tag / input type / role / <form> membership / form method) that browser.py
#      extracts independently of the LLM, so a plain "Submit"/"Apply"/"जमा करें" button — or ANY
#      label, in any language — is caught by structure, not words.
#   2. This keyword list — defense-in-depth for JS-only submits that have no real <form> element
#      (so no structural signal) and for other sensitive controls. ONE source of truth for the
#      "never auto-fill" set: reuse form_analyzer's richer classification, then add generic
#      submit / final-action verbs and Hindi/Devanagari + romanized equivalents.
from src.tasks.form_analyzer import _SENSITIVE as _FORM_SENSITIVE

_SUBMIT_VERBS = (
    "submit", "final submit", "apply", "register", "sign up", "signup", "create account",
    "send", "save", "post", "confirm", "continue", "next", "proceed", "finish", "book",
    "reserve", "file", "e-sign", "esign", "verify otp", "place application",
    # login / commerce controls (kept explicit from the original list):
    "login", "log in", "sign in", "pay now", "make payment", "proceed to pay",
    "confirm & pay", "confirm and pay", "proceed to buy", "proceed to checkout",
    "place order", "buy now", "continue to payment", "place your order",
)
# Hindi / Devanagari + common romanized equivalents of the submit / final-action verbs above.
_SUBMIT_VERBS_HI = (
    "जमा करें", "जमा करे", "आगे बढ़ें", "आगे बढे", "भेजें", "भेजे", "सहेजें", "सहेजे",
    "पुष्टि करें", "पुष्टि करे", "जारी रखें", "पंजीकरण करें", "पंजीकरण", "लॉगिन",
    "भुगतान करें", "भुगतान करे", "जमा", "आगे बढ़ो",
    "jama karein", "jama karo", "aage badhein", "aage badho", "bhejein", "bhejo",
    "sahejein", "pushti karein", "jari rakhein", "panjikaran", "bhugtan karein",
)
# De-duplicated, order-preserved single source of truth for the acting agent's keyword backstop.
_SENSITIVE_ELEMENT = tuple(dict.fromkeys(tuple(_FORM_SENSITIVE) + _SUBMIT_VERBS + _SUBMIT_VERBS_HI))


async def _wait_human_live(session, browser) -> bool:
    """Wait for the user to finish a hand-off step while STREAMING the live view, so their own
    clicks/typing (forwarded to the browser) are visible. Refreshes ~every 1.3s.

    BOUNDED: if the user never taps 'I've done it' and the WS never cleanly closes, this would
    otherwise block the agent + the live server browser FOREVER. After IPA_HUMAN_WAIT_TIMEOUT
    seconds we give up, mark the run FAILED, and raise so run_task's handler closes the browser."""
    session._human_flag = False
    since = 0.0
    waited = 0.0
    timeout = float(getattr(settings, "IPA_HUMAN_WAIT_TIMEOUT", 600))   # default 10 minutes
    while not session._human_flag and not session._stop:
        await asyncio.sleep(0.4)
        since += 0.4
        waited += 0.4
        if timeout > 0 and waited >= timeout:
            log.warning("ipa_human_wait_timeout", task_id=session.task_id, waited_s=round(waited))
            session.status = RunStatus.FAILED
            await session.emit(event("needs_human", session.task_id,
                                     reason=f"Timed out after {int(timeout // 60)} min waiting for you to "
                                            "complete the hand-off.",
                                     instruction="The run was stopped for safety — start again when ready."))
            # Raise so run_task marks the run FAILED and its `finally` closes the live browser
            # (leaving it open would strand a real Chromium page on the server).
            raise TimeoutError(
                f"Hand-off timed out after {int(timeout // 60)} min with no confirmation — "
                "stopped for safety.")
        if since >= 1.3:
            since = 0.0
            shot = await browser.clean_shot()
            if shot:
                await session.emit(event("screenshot", session.task_id, image=shot,
                                         url=browser.current_url))
    return session._human_flag and not session._stop


def _sensitive_text(text: str) -> bool:
    return any(k in (text or "").lower() for k in _SENSITIVE_ELEMENT)


# ── Deterministic auth / login / OTP PAGE detector (page-level hand-off) ───────
# Complements the element-level guards (_is_sensitive_target / _is_final_submit): when the
# WHOLE current page is a sign-in / OTP / auth screen, hand control to the user BEFORE the
# agent attempts anything on it — so it never fumbles a Google "this browser may not be
# secure" wall or types into a login form. Decided from URL + DOM STRUCTURE, never from the
# LLM. Deliberately precise (real password/OTP input or an auth URL) so an ordinary page that
# merely has a "Sign in" link in its header is NOT misclassified as an auth page.
_AUTH_URL_SIGNALS = (
    "accounts.google.com", "login.microsoftonline.com", "appleid.apple.com",
    "login.", "signin.", "auth.", "sso.", "oauth", "openid",
    "/login", "/signin", "/sign-in", "/sign_in", "/auth", "/session/new",
    "/account/login", "/accounts/login", "/users/sign_in", "/saml", "/mfa", "/2fa",
)
# OTP / one-time-code field hints (name / placeholder / aria-label / visible text).
_OTP_HINTS = ("otp", "one-time", "one time", "verification code", "verify code",
              "auth code", "authentication code", "2fa", "passcode", "ओटीपी", "एक बार")


def _is_auth_page(url: str, elements: list[dict]) -> tuple[bool, str]:
    """Return (is_auth, kind) when the CURRENT page is a login / sign-in / OTP / auth screen.

    kind is "login" or "otp". Structural + LLM-independent: an auth-looking URL, OR a visible
    password input, OR an OTP/one-time-code field. Used to hand off the WHOLE page up-front."""
    u = (url or "").lower()
    if any(sig in u for sig in _AUTH_URL_SIGNALS):
        return True, "login"
    for e in elements:
        if e.get("type") == "password":
            return True, "login"
        if e.get("tag") in ("input", "textarea"):
            blob = " ".join(str(e.get(k, "")) for k in ("text", "placeholder", "role")).lower()
            if any(h in blob for h in _OTP_HINTS):
                return True, "otp"
    return False, ""


async def _hand_back(session, browser, step, reason: str, instruction: str) -> bool:
    """Transition to the 'you're in control' hand-off state, stream the live view while the user
    acts, and resume when they tap 'I've done it'. Returns True to continue, False if the run was
    stopped or the wait failed/timed out. Shared by the auth-page guard on both the live loop and
    the replay fast-path so the hand-off behaves identically everywhere."""
    if step is not None:
        step.status = StepStatus.NEEDS_HUMAN
    session.status = RunStatus.NEEDS_HUMAN
    log.info("ipa_handoff", task_id=session.task_id,
             step_id=(step.id if step is not None else None), reason=reason[:80])
    narrate.handoff(session.task_id, "auth", reason)
    await session.emit(event("needs_human", session.task_id,
                             step_id=(step.id if step is not None else None),
                             reason=reason, instruction=instruction))
    ok = await _wait_human_live(session, browser)
    if session.stopped or not ok:
        log.info("ipa_handoff_abandoned", task_id=session.task_id, stopped=session.stopped)
        return False
    log.info("ipa_handoff_resumed", task_id=session.task_id)
    narrate.resumed(session.task_id)
    session.status = RunStatus.RUNNING
    session._form_dirty = False   # the human took over any form on this page
    return True


def _auth_handoff_copy(kind: str) -> tuple[str, str]:
    """User-facing (reason, instruction) for an auth-page hand-off."""
    if kind == "otp":
        reason = ("This page needs the OTP / verification code sent to you — "
                  "I never handle one-time codes, so please enter it yourself.")
    else:
        reason = ("This page needs your sign-in — I don't handle passwords or logins. "
                  "Everything non-secret is already filled; just sign in.")
    return reason, "Sign in / enter the code in the view, then tap 'I've done it' to continue."


def _find_by_text(elements: list[dict], target: str, tag: str | None = None) -> dict | None:
    """Match a recipe's recorded element to the CURRENT page by its visible text (indices change
    across runs, text usually doesn't). Returns the best match or None if nothing is close."""
    t = " ".join((target or "").split()).lower()
    if not t:
        return None
    best, best_score = None, 0.0
    for e in elements:
        et = " ".join((e.get("text") or "").split()).lower()
        if not et:
            continue
        if et == t:
            score = 3.0
        elif t in et or et in t:
            score = 2.0
        else:
            a, b = set(t.split()), set(et.split())
            score = 1.0 if (a and b and len(a & b) / len(a | b) >= 0.5) else 0.0
        if tag and e.get("tag") == tag:
            score += 0.5
        if score > best_score:
            best_score, best = score, e
    return best if best_score >= 2.0 else None


async def _try_replay(session: TaskSession, browser) -> bool:
    """FAST PATH: replay a proven recipe deterministically (no per-step LLM). Matches recorded
    actions to the live page by element text, resolves values from the user's answers, and hands
    off sensitive steps. Returns True if it drove the whole task; False (after re-navigating to the
    start) to fall back to the LLM loop when the page diverges. Best-effort — never raises."""
    try:
        from src.ipa.recipes import find_recipe
        recipe = await find_recipe(session.goal, session.plan.start_url)
    except Exception:
        recipe = None
    trace = (recipe or {}).get("trace") or []
    # Only replay a well-proven, closely-matching recipe.
    if not recipe or not trace or recipe.get("success_count", 1) < 2 or recipe.get("score", 0) < 0.5:
        return False

    await session.emit(event("message", session.task_id,
                             text=f"Replaying a proven recipe for {recipe.get('host', 'this site')} "
                                  f"(used {recipe.get('success_count')}× before)…"))
    log.info("ipa_replay_start", task_id=session.task_id, host=recipe.get("host"),
             success_count=recipe.get("success_count"), score=recipe.get("score"), steps=len(trace))
    narrate.replay(session.task_id, str(recipe.get("host", "this site")),
                   int(recipe.get("success_count", 0) or 0))
    for t in trace:
        if session.stopped:
            return True
        await session.wait_if_paused()
        clean, marked, elements, url, title = await browser.perceive()
        await session.emit(event("screenshot", session.task_id, image=clean, url=url, title=title))
        # Same page-level auth/OTP hand-off on the deterministic replay fast-path: a recorded
        # recipe must never drive a login/OTP page either.
        is_auth, auth_kind = _is_auth_page(url, elements)
        if is_auth:
            reason, instruction = _auth_handoff_copy(auth_kind)
            if not await _hand_back(session, browser, None, reason, instruction):
                return True
            continue
        atype = t.get("action", "")
        target = t.get("target", "")
        value = session.answers.get(t["value_key"]) if t.get("value_key") else t.get("value")

        if atype in ("scroll", "wait", "navigate"):
            await browser.act(atype, None, str(value or t.get("value") or ""))
            continue
        if _sensitive_text(target):     # login/OTP/payment recorded → hand off
            session.status = RunStatus.NEEDS_HUMAN
            log.info("ipa_replay_handoff", task_id=session.task_id, kind="sensitive", target=target[:40])
            narrate.handoff(session.task_id, "sensitive", "recorded login / OTP / payment step")
            await session.emit(event("needs_human", session.task_id,
                                     reason="This step needs your login / OTP / payment.",
                                     instruction="Take over in the view, then tap 'I've done it'."))
            if not await _wait_human_live(session, browser) or session.stopped:
                return True
            narrate.resumed(session.task_id)
            session.status = RunStatus.RUNNING
            continue
        el = _find_by_text(elements, target, t.get("target_tag"))
        if el is None:
            log.info("ipa_replay_diverged", task_id=session.task_id, target=target[:40])
            narrate.note(session.task_id, f"page diverged from recipe at '{target[:40]}' — switching to live navigation")
            await session.emit(event("message", session.task_id,
                                     text="The page differs from the saved recipe — switching to live navigation."))
            await browser.goto(session.plan.start_url)   # reset so the LLM loop starts clean
            return False
        # SAME deterministic guard on the replay fast-path: a recorded recipe must NEVER auto-submit
        # a real form either. Rebuild an action against the LIVE element descriptor and re-check.
        replay_action = AgentAction(type=atype, index=el["index"], text=str(value or ""))
        if _is_final_submit(replay_action, elements, session) or _is_sensitive_target(replay_action, elements):
            session.status = RunStatus.NEEDS_HUMAN
            await session.emit(event("needs_human", session.task_id,
                                     reason="I've filled the form and stopped before submitting it — "
                                            "please review and submit/confirm this yourself.",
                                     instruction="Review and submit in the view, then tap 'I've done it'."))
            if not await _wait_human_live(session, browser) or session.stopped:
                return True
            session.status = RunStatus.RUNNING
            session._form_dirty = False
            continue
        outcome = await browser.act(atype, el["index"], str(value or ""))
        if atype in ("type", "select") and "failed" not in outcome:
            session._form_dirty = True
        log.debug("ipa_replay_action", task_id=session.task_id, action=atype, target=target[:40], outcome=outcome)
        narrate.action(session.task_id, atype, target, outcome, thought="replay")
        await session.emit(event("action", session.task_id, thought=f"Replaying: {atype} {target[:30]}",
                                 action={"type": atype, "index": el["index"], "text": str(value or "")},
                                 outcome=outcome))
        if "failed" in outcome:
            log.info("ipa_replay_action_failed", task_id=session.task_id, action=atype, target=target[:40])
            narrate.note(session.task_id, f"replay action failed ({atype}) — switching to live navigation")
            await browser.goto(session.plan.start_url)
            return False

    # Whole recipe replayed — mark the checklist done.
    for s in session.plan.steps:
        if s.status not in (StepStatus.NEEDS_HUMAN, StepStatus.DONE):
            s.status = StepStatus.DONE
            await session.emit(event("step", session.task_id, step_id=s.id, status="done", title=s.title))
    log.info("ipa_replay_completed", task_id=session.task_id)
    return True


_AGENT_SYSTEM = """You are a careful web-browser agent working ONE step of a checklist for an
Indian user. You are given: the overall goal, the CURRENT step, the page URL, and the list of
interactive elements — each with an [index], its tag/role and its visible text. A screenshot may
also be provided, but PREFER the element list; use the image only to disambiguate.

Return the next 1-3 actions to advance the CURRENT step, as STRICT JSON:
{"thought": "one short sentence on what you're doing",
 "actions": [ {"type": "click|type|select|press|scroll|navigate|wait|done|ask_human", "index": <int or null>, "text": "<text/url/option/key>"} ]}

Rules:
- BATCH only actions that run WITHOUT the page reloading in between (e.g. type into field A, type
  into field B, then click Search). Put any page-changing click/navigate/press LAST in the list.
- Use an element's [index] for click/type/select/press.
- To SUBMIT a search box that has no visible Search button (e.g. it says "Press Enter to search"),
  use {"type":"press","index":<the search field>,"text":"Enter"}. Do NOT look for an on-screen
  "Enter" key or button to click — there is none; `press` sends the real keyboard key. Prefer
  pressing Enter in the field over clicking when the field is the only search control.
- Use a SINGLE action {"type":"done"} when the step's goal is clearly achieved on the page.
- Use a SINGLE action {"type":"ask_human", ...} for a login / OTP / password / payment / final
  submit/confirm, or when you are stuck. NEVER type passwords, OTPs, or card details yourself.
- Do not repeat an action that just failed; try another element or scroll. Keep `text` short/exact."""


def _elements_text(elements: list[dict]) -> str:
    lines = []
    for e in elements[:100]:
        t = e.get("tag", "")
        typ = f" type={e['type']}" if e.get("type") else ""
        txt = f' "{e["text"]}"' if e.get("text") else ""
        lines.append(f'[{e["index"]}] <{t}{typ}>{txt}')
    return "\n".join(lines) or "(no interactive elements found)"


def _clean_json(text: str) -> str:
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].split("```")[0].replace("json", "", 1).strip()
    if not t.startswith("{"):
        s, e = t.find("{"), t.rfind("}")
        if s != -1 and e > s:
            t = t[s:e + 1]
    return t


def _is_enter_key(text: str) -> bool:
    """A `press` whose key submits a form. Enter/Return (and an empty key, which browser.act
    defaults to Enter) submit; navigation keys like Tab/Escape/arrows do not."""
    return (text or "").strip().lower() in ("", "enter", "return", "\n", "\r", "numpadenter")


def _is_sensitive_target(action: AgentAction, elements: list[dict]) -> bool:
    # Typing OR pressing a key into a password field is sensitive (login). Page-level auth
    # detection normally hands these off first; this is defence-in-depth for both actions.
    if action.type in ("type", "press") and action.index is not None:
        el = next((e for e in elements if e.get("index") == action.index), None)
        if el and el.get("type") == "password":
            return True
    hay = (action.text or "").lower()
    if action.index is not None:
        el = next((e for e in elements if e.get("index") == action.index), None)
        if el:
            hay += " " + (el.get("text") or "").lower()
    return any(k in hay for k in _SENSITIVE_ELEMENT)


def _is_final_submit(action: AgentAction, elements: list[dict], session: TaskSession) -> bool:
    """PRIMARY, DETERMINISTIC final-submit guard — decided purely from DOM STRUCTURE, never from
    the LLM's words. Returns True when performing this click would submit a real form (a
    state-changing POST) so the run must hand off to the human instead of auto-submitting.

    The TWO ways to submit a real form from the agent's action vocabulary are gated here:
      • `click` on a submit-capable control, and
      • `press` Enter inside a form field (keyboard submit — e.g. a search box with no Search
        button, or hitting Enter in a login/checkout field).
    `type` uses page.fill (no Enter dispatched), `navigate` is a plain GET, and other keys
    (Tab/Escape/arrows) don't submit — so click + Enter-press cover every submit path.

    Why this cannot be bypassed by the LLM:
      • The signals (tag, input `type`, role, <form> membership, form `method`, and whether the
        agent has already filled a field this run) come from browser.py's own DOM extraction and
        the session's own action bookkeeping — not from anything the model returns. No prompt or
        JSON the LLM emits can change the verdict.

    Structural rule (fail-safe — err toward pausing):
      A GET form is a query/search (navigation, not a state change) — allowed. Any other method
      (POST/dialog/unknown) is treated as a final submission and handed off:
        - click: final submit if it is a submit-capable control in a non-GET form, OR the agent has
          already filled ≥1 field in a form and this click targets a control in a non-GET form.
        - press Enter: final submit if pressed inside a non-GET form. When no target index is given
          we cannot read the form method, so if the agent has filled a form this run we hand off
          (fail-safe); the prompt asks the model to include the field index so the normal GET-search
          Enter stays allowed.
    """
    is_click = action.type == "click"
    is_enter = action.type == "press" and _is_enter_key(action.text)
    if not (is_click or is_enter):
        return False

    if action.index is None:
        # Enter with no known target: can't verify the form's method structurally. Hand off only
        # if a form has been filled this run (a bare Enter that could submit it). A click always
        # carries an index, so this branch is Enter-only.
        return is_enter and bool(getattr(session, "_form_dirty", False))

    el = next((e for e in elements if e.get("index") == action.index), None)
    if not el:
        return False
    in_form = bool(el.get("in_form"))
    if not in_form:
        return False   # no real <form> → no structural signal; the keyword backstop covers this
    method = (el.get("form_method") or "get").lower()
    if method == "get":
        return False   # search / query form → allowed (navigation, not a state-changing submit)
    if is_enter:
        return True     # Enter inside a non-GET form submits it → hand off
    submit_capable = bool(el.get("submits"))
    # A form the agent has already typed/selected into, now being clicked → treat as its submit.
    return submit_capable or bool(getattr(session, "_form_dirty", False))


def _to_action(a: dict, thought: str = "") -> AgentAction | None:
    if not isinstance(a, dict) or not a.get("type"):
        return None
    idx = a.get("index")
    return AgentAction(
        type=str(a.get("type", "wait")),
        index=int(idx) if isinstance(idx, (int, float)) or (isinstance(idx, str) and str(idx).isdigit()) else None,
        text=str(a.get("text", "")),
        thought=thought,
    )


async def _decide(session: TaskSession, step, url: str, title: str, elements: list[dict],
                  screenshot: str, tried: list[str]) -> list[AgentAction]:
    """Decide the next 1-3 actions for the CURRENT step. TEXT-FIRST for speed (the element list is
    usually enough — no image upload); falls back to VISION only if the text pass returns nothing.
    Returns a batch of actions to execute in sequence."""
    prompt = (
        f"GOAL: {session.goal}\n"
        f"CURRENT STEP: {step.title} — {step.detail}\n"
        f"USER-PROVIDED DETAILS: {json.dumps(session.answers, ensure_ascii=False)}\n"
        f"PAGE: {title} ({url})\n"
        f"RECENT ACTIONS: {'; '.join(tried[-4:]) or 'none'}\n\n"
        f"INTERACTIVE ELEMENTS:\n{_elements_text(elements)}"
    )
    for use_image in (False, True):   # TEXT first (fast); vision fallback only if needed
        content = [{"type": "text", "text": prompt}]
        if use_image and screenshot:
            content.append({"type": "image_url", "image_url": {"url": screenshot}})
        try:
            resp = await asyncio.wait_for(
                route_completion(
                    messages=[{"role": "system", "content": _AGENT_SYSTEM},
                              {"role": "user", "content": content}],
                    override_tier="primary", correlation_id=session.task_id),
                timeout=18,
            )
            raw = (resp.content or "").strip()
            if not raw:
                continue
            data = json.loads(_clean_json(raw))
            thought = str(data.get("thought", ""))[:200]
            raw_acts = data.get("actions")
            if not isinstance(raw_acts, list) or not raw_acts:
                a = data.get("action")
                raw_acts = [a] if isinstance(a, dict) else []
            out = [x for x in (_to_action(a, thought if i == 0 else "")
                               for i, a in enumerate(raw_acts[:4])) if x]
            if out:
                return out
        except Exception as exc:
            log.warning("ipa_decide_failed", error=str(exc),
                        attempt="text" if not use_image else "vision", task_id=session.task_id)
    return [AgentAction(type="ask_human", reason="I could not decide the next step — please guide me.")]


async def _persist_success(session: TaskSession) -> None:
    """Save the reusable recipe (shared) + the user's durable personal facts (private)."""
    from urllib.parse import urlparse
    try:
        host = urlparse(session.plan.start_url or "").netloc.replace("www.", "").lower()
        from src.ipa.recipes import save_recipe
        await save_recipe(
            host=host, goal=session.goal, start_url=session.plan.start_url,
            steps=[s.to_dict() for s in session.plan.steps], trace=session.trace,
            form_fields=[f.to_dict() for f in session.plan.form_fields], created_by=session.user_id,
        )
    except Exception as exc:
        log.debug("recipe_persist_skipped", error=str(exc))
    try:
        from src.agents.memory_extractor import learn_and_persist
        await learn_and_persist(
            query=session.goal, clarifications=session.answers, existing_profile={},
            user_id=session.user_id, session_id=session.task_id, correlation_id=session.task_id,
        )
    except Exception as exc:
        log.debug("profile_learn_skipped", error=str(exc))


async def run_task(session: TaskSession) -> None:
    """Execute the whole checklist. Streams events to session.queue. Never raises."""
    browser = BrowserSession()
    session.browser = browser   # expose for user remote-control during a hand-off
    # Bind the run's identity into structlog contextvars so EVERY nested ipa.* log (browser,
    # planner, recipes, executors …) auto-carries task_id/user_id without each call passing
    # them — IPA runs on its own background task/loop, so it doesn't inherit the request's
    # correlation context. correlation_id is set to task_id (the IPA run's stable trace key).
    import structlog.contextvars as _ctx
    _ctx.bind_contextvars(task_id=session.task_id, user_id=session.user_id,
                          correlation_id=session.task_id, flow="ipa")
    try:
        session.status = RunStatus.RUNNING
        log.info("ipa_task_start", task_id=session.task_id, user_id=session.user_id,
                 goal=(session.goal or "")[:120], start_url=session.plan.start_url,
                 steps=len(session.plan.steps))
        narrate.task_start(session.task_id, session.user_id, session.goal, session.plan.start_url)
        # Persist RUNNING so a WS landing on ANOTHER worker sees the task is already live and does
        # NOT launch a second browser run (see load_session / task_agent start guard).
        await persist_session(session)
        await session.emit(event("status", session.task_id, status=session.status.value))
        await session.emit(event("message", session.task_id,
                                  text=f"Starting — opening {session.plan.start_url}"))
        await browser.start(session.plan.start_url)

        # FAST PATH — replay a proven recipe deterministically (no per-step LLM). If the page has
        # diverged it returns False and the LLM loop below drives it live.
        replayed = await _try_replay(session, browser)

        for step in session.plan.steps:
            if replayed or session.stopped:
                break
            await session.wait_if_paused()
            step.status = StepStatus.RUNNING
            log.info("ipa_step_start", task_id=session.task_id, step_id=step.id,
                     title=(step.title or "")[:80], sensitive=bool(step.sensitive))
            narrate.step_start(session.task_id, step.id, step.title, bool(step.sensitive))
            await session.emit(event("step", session.task_id, step_id=step.id,
                                     status=step.status.value, title=step.title))

            # Sensitive step → hand to the user, wait for them to finish, then continue.
            if step.sensitive:
                clean, marked, elements, url, title = await browser.perceive()
                await session.emit(event("screenshot", session.task_id, image=clean, url=url, title=title))
                step.status = StepStatus.NEEDS_HUMAN
                session.status = RunStatus.NEEDS_HUMAN
                log.info("ipa_handoff", task_id=session.task_id, step_id=step.id, kind="sensitive_step")
                narrate.handoff(session.task_id, "sensitive", "login / OTP / payment / final submit")
                await session.emit(event("needs_human", session.task_id, step_id=step.id,
                                         reason="This step needs your login / OTP / payment / final submit.",
                                         instruction=f"Please complete: {step.title}. Then tap 'I've done it'."))
                ok = await _wait_human_live(session, browser)
                if session.stopped or not ok:
                    log.info("ipa_step_abandoned", task_id=session.task_id, step_id=step.id, stopped=session.stopped)
                    break
                step.status = StepStatus.DONE
                session.status = RunStatus.RUNNING
                narrate.resumed(session.task_id)
                narrate.step_done(session.task_id, step.id, "done")
                await session.emit(event("step", session.task_id, step_id=step.id,
                                         status=step.status.value, title=step.title))
                continue

            # Automatable step → agent loop (BATCHED: one LLM decision yields 1-3 actions, so far
            # fewer round-trips per step). Re-perceive only after a page-changing action or failure.
            tried: list[str] = []
            done = False
            # A step is only a real FAILURE when NOTHING worked. `progressed` records that the
            # agent did meaningful work on this step — a successful action, or a completed human
            # hand-off — so a step that advanced the task is marked DONE even if the LLM never
            # emitted an explicit {"type":"done"} (LLMs frequently under-report completion, which
            # otherwise flipped genuinely-successful steps to FAILED — the reported failure mode).
            progressed = False
            for _ in range(_MAX_DECISIONS_PER_STEP):
                if session.stopped:
                    break
                await session.wait_if_paused()
                clean, marked, elements, url, title = await browser.perceive()
                await session.emit(event("screenshot", session.task_id, image=clean, url=url,
                                         title=title, elements=len(elements)))
                # PAGE-LEVEL HAND-OFF: if the whole page is a login / sign-in / OTP screen, hand
                # control to the user BEFORE deciding/acting — decided structurally (URL + DOM),
                # never from the LLM — so the agent never types into a login form or fumbles a
                # "browser not secure" wall. Resume the same step after the human signs in.
                is_auth, auth_kind = _is_auth_page(url, elements)
                if is_auth:
                    reason, instruction = _auth_handoff_copy(auth_kind)
                    if not await _hand_back(session, browser, step, reason, instruction):
                        break
                    continue   # re-perceive after the human finishes
                actions = await _decide(session, step, url, title, elements, marked, tried)

                for action in actions:
                    if session.stopped:
                        break
                    if action.type == "done":
                        done = True
                        break
                    # DETERMINISTIC HAND-OFF: ask_human, a sensitive keyword match, OR — the primary
                    # guarantee — a STRUCTURAL final-submit (this click would submit a real form).
                    # `_is_final_submit` is evaluated in code from the DOM descriptor, so no LLM plan
                    # can route a form submission / final action past this point.
                    final_submit = _is_final_submit(action, elements, session)
                    if action.type == "ask_human" or _is_sensitive_target(action, elements) or final_submit:
                        step.status = StepStatus.NEEDS_HUMAN
                        session.status = RunStatus.NEEDS_HUMAN
                        reason = (action.reason or action.thought or "I need your help here.")
                        if final_submit:
                            reason = ("I've filled the form and stopped before submitting it — "
                                      "please review and submit/confirm this yourself.")
                        kind = "final_submit" if final_submit else ("ask_human" if action.type == "ask_human" else "sensitive")
                        log.info("ipa_handoff", task_id=session.task_id, step_id=step.id,
                                 kind=kind, reason=reason[:80])
                        narrate.handoff(session.task_id, kind, reason)
                        await session.emit(event("needs_human", session.task_id, step_id=step.id,
                                                 reason=reason,
                                                 instruction="Review and submit in the view, then tap 'I've done it' to hand back."))
                        ok = await _wait_human_live(session, browser)
                        if session.stopped or not ok:
                            break
                        progressed = True   # a completed hand-off is real progress on this step
                        session.status = RunStatus.RUNNING
                        session._form_dirty = False   # the human took over this form
                        narrate.resumed(session.task_id)
                        break     # re-perceive after the human's changes
                    outcome = await browser.act(action.type, action.index, action.text)
                    if "failed" not in outcome:
                        progressed = True
                    # Track that the agent has entered data into a form this run, so the NEXT click
                    # inside a (non-GET) form is treated as its submit and handed off (fail-safe).
                    if action.type in ("type", "select") and "failed" not in outcome:
                        session._form_dirty = True
                    tried.append(f"{action.type}#{action.index}:{outcome}")
                    _record_trace(session, step, action, elements, outcome)
                    log.debug("ipa_action", task_id=session.task_id, step_id=step.id,
                              action=action.type, index=action.index, outcome=outcome)
                    narrate.action(session.task_id, action.type,
                                   target=(action.text or ""), outcome=outcome, thought=action.thought)
                    await session.emit(event("action", session.task_id, thought=action.thought,
                                             action=action.to_dict(), outcome=outcome))
                    # A page-changing action (or a failure) invalidates the remaining indices —
                    # stop this batch and re-perceive on the next iteration.
                    if action.type in ("click", "navigate", "press") or "failed" in outcome:
                        break
                if done:
                    break

            # DONE if the agent self-reported completion OR did real work; FAILED only when the
            # step made no progress at all (every attempt errored, or the agent was immediately
            # stuck). This stops well-executed steps from being mislabelled as failures.
            step.status = StepStatus.DONE if (done or progressed) else StepStatus.FAILED
            log.info("ipa_step_done", task_id=session.task_id, step_id=step.id,
                     status=step.status.value, self_reported=done, progressed=progressed)
            narrate.step_done(session.task_id, step.id, step.status.value)
            await session.emit(event("step", session.task_id, step_id=step.id,
                                     status=step.status.value, title=step.title))

        # Final state.
        if session.stopped:
            session.status = RunStatus.STOPPED
        elif any(s.status == StepStatus.DONE for s in session.plan.steps):
            # Partial or full success. A task that reached the cart / hand-off did real work — do
            # NOT scream "Failed" just because one tricky automatable step (e.g. Apply Filters)
            # never reported 'done'. Only a run where NOTHING worked is a failure.
            session.status = RunStatus.DONE
        else:
            session.status = RunStatus.FAILED
        # Persist the TERMINAL status so the run is no longer seen as RUNNING by another worker
        # (otherwise the start/relaunch guard would refuse a legitimate fresh run for this task).
        await persist_session(session)
        clean, _marked, _els, url, title = await browser.perceive()
        await session.emit(event("screenshot", session.task_id, image=clean, url=url, title=title))
        # Include the FINAL page URL so the client can offer a "open the result page" link — the
        # user can revisit the result/confirmation page in their own browser after the run.
        log.info("ipa_task_end", task_id=session.task_id, status=session.status.value,
                 success=session.status == RunStatus.DONE, url=url,
                 steps_done=sum(1 for s in session.plan.steps if s.status == StepStatus.DONE),
                 steps_total=len(session.plan.steps))
        narrate.task_end(session.task_id, session.status.value,
                         session.status == RunStatus.DONE, url=url, title=title)
        await session.emit(event("done", session.task_id, status=session.status.value,
                                 success=session.status == RunStatus.DONE, url=url, title=title))

        # On success: (1) save a REUSABLE recipe (the how — shared, personal-data-free) so similar
        # tasks run better for any user, and (2) learn this user's durable PERSONAL facts into their
        # own profile (private) for better future plans. Both best-effort, after delivery.
        if session.status == RunStatus.DONE:
            await _persist_success(session)
    except Exception as exc:
        import traceback
        etype = type(exc).__name__
        # Empty-message errors (e.g. NotImplementedError from a non-Proactor loop) still get a
        # useful label + traceback in the logs and a non-empty message in the UI.
        msg = str(exc) or etype or "Execution failed"
        if etype == "NotImplementedError":
            msg = "The browser could not start on this server (event-loop/subprocess issue)."
        log.error("ipa_run_failed", error=str(exc), error_type=etype,
                  trace=traceback.format_exc()[-900:], task_id=session.task_id)
        narrate.note(session.task_id, f"run failed [{etype}]: {msg[:100]}")
        narrate.task_end(session.task_id, "failed", False)
        session.status = RunStatus.FAILED
        # Persist FAILED too (covers the hand-off-timeout raise): clears the RUNNING lock so the
        # user can start over, and never leaves a dead task looking live to other workers.
        try:
            await persist_session(session)
        except Exception:
            pass
        await session.emit(event("error", session.task_id, message=msg[:200]))
    finally:
        await browser.close()
        log.debug("ipa_browser_closed", task_id=session.task_id)
        # Drop the run's contextvars so they never leak into a later task on this context.
        _ctx.unbind_contextvars("task_id", "user_id", "correlation_id", "flow")
