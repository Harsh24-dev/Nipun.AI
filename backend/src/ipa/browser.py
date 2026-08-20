"""
Browser perception + action, via Playwright.

The agent sees the page the way a modern browser-use agent does — NOT as raw pixels, but as a
compact list of the INTERACTIVE elements, each tagged with an index and drawn as a numbered box
on the screenshot (the "set-of-marks" technique). The LLM then references an element by its index
(`click 12`), and we act on the real DOM node via a stable `data-ipa-index` attribute — far more
reliable than guessing pixel coordinates.

Playwright is imported lazily so the app runs even when the browser binary is not installed
(`playwright install chromium`).
"""

from __future__ import annotations

import base64

from src.core.logging import get_ipa_logger

log = get_ipa_logger("ipa.browser")

# JS that marks every visible interactive element with data-ipa-index, draws a labelled overlay
# box for each, and returns their descriptors. Re-run each perceive; it clears prior marks first.
_MARK_JS = r"""
() => {
  const OLD = document.getElementById('__ipa_overlay__');
  if (OLD) OLD.remove();
  document.querySelectorAll('[data-ipa-index]').forEach(e => e.removeAttribute('data-ipa-index'));

  const overlay = document.createElement('div');
  overlay.id = '__ipa_overlay__';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;pointer-events:none;';
  document.body.appendChild(overlay);

  const SEL = 'a,button,input,select,textarea,[role=button],[role=link],[role=checkbox],' +
              '[role=tab],[role=menuitem],[onclick],[contenteditable=true],summary,label';
  const nodes = Array.from(document.querySelectorAll(SEL));
  const out = [];
  let i = 0;
  const seen = new Set();
  for (const el of nodes) {
    if (seen.has(el)) continue;
    const r = el.getBoundingClientRect();
    const st = window.getComputedStyle(el);
    const visible = r.width > 2 && r.height > 2 && st.visibility !== 'hidden' &&
                    st.display !== 'none' && parseFloat(st.opacity || '1') > 0.05 &&
                    r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
    if (!visible) continue;
    if (el.disabled) continue;
    seen.add(el);
    el.setAttribute('data-ipa-index', i);
    const label = (el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                   el.getAttribute('name') || el.value || el.innerText || el.getAttribute('title') || '')
                  .replace(/\s+/g, ' ').trim().slice(0, 80);
    // STRUCTURAL submit metadata (used by the agent's deterministic final-submit interception,
    // independent of the LLM). `in_form`/`form_method` describe the enclosing <form>; `submits`
    // is true for a control whose activation submits that form.
    const tagName = el.tagName.toLowerCase();
    const rawType = (el.getAttribute('type') || '').toLowerCase();
    const roleAttr = (el.getAttribute('role') || '').toLowerCase();
    const form = el.closest('form');
    const inForm = !!form;
    const formMethod = form ? (form.method || 'get').toLowerCase() : '';
    let submits = false;
    if (tagName === 'input' && (rawType === 'submit' || rawType === 'image')) {
      submits = true;                              // <input type=submit|image>
    } else if (tagName === 'button' && (rawType === 'submit' || rawType === '')) {
      // <button type=submit> OR a bare <button> — HTML defaults an in-form button to type=submit.
      submits = inForm;
    } else if (roleAttr === 'button' && inForm) {
      submits = true;                              // role=button inside a form → may submit it
    }
    out.push({
      index: i, tag: tagName,
      type: rawType,
      role: el.getAttribute('role') || '',
      text: label,
      placeholder: el.getAttribute('placeholder') || '',
      in_form: inForm, form_method: formMethod, submits: submits,
      x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
    });
    // draw the marker box + index label
    const box = document.createElement('div');
    const isInput = ['input','textarea','select'].includes(el.tagName.toLowerCase());
    const color = isInput ? '#2563eb' : '#dc2626';
    box.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;` +
      `height:${r.height}px;border:2px solid ${color};box-sizing:border-box;border-radius:3px;`;
    const tag = document.createElement('div');
    tag.textContent = i;
    tag.style.cssText = `position:fixed;left:${r.left}px;top:${Math.max(0,r.top-15)}px;background:${color};` +
      'color:#fff;font:bold 11px sans-serif;padding:0 3px;border-radius:3px;line-height:15px;';
    overlay.appendChild(box); overlay.appendChild(tag);
    i++;
    if (i >= 120) break;
  }
  return out;
}
"""

_CLEAR_JS = "() => { const o=document.getElementById('__ipa_overlay__'); if(o) o.remove(); }"


class BrowserSession:
    """A single live Chromium page the agent drives. One per task run."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    async def start(self, start_url: str) -> None:
        log.info("ipa_browser_starting", start_url=(start_url or "")[:120])
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        # Headless is fine — the user watches via the streamed screenshots. A real UA + viewport
        # keeps sites behaving normally.
        self._browser = await self._pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
            locale="en-IN",
        )
        self.page = await self._context.new_page()
        self.page.set_default_timeout(15000)
        await self.goto(start_url)
        log.info("ipa_browser_started", url=self.current_url)

    async def goto(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        log.info("ipa_navigate", url=url[:120])
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(600)
        except Exception as exc:
            log.warning("ipa_goto_failed", url=url[:120], error=str(exc),
                        error_type=type(exc).__name__)

    async def _shot(self) -> str:
        # JPEG (not PNG) — ~5-10× smaller, so both the live stream AND the vision LLM calls are
        # markedly faster (the screenshot payload was the biggest latency driver in the loop).
        try:
            jpg = await self.page.screenshot(type="jpeg", quality=65, full_page=False)
            return "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")
        except Exception as exc:
            log.warning("ipa_screenshot_failed", error=str(exc), error_type=type(exc).__name__)
            return ""

    async def perceive(self) -> tuple[str, str, list[dict], str, str]:
        """Return (clean_shot, marked_shot, elements, url, title).

        `clean_shot` is streamed to the USER — a normal page view with NO overlay. `marked_shot`
        carries the numbered element boxes and is fed ONLY to the agent's vision model so it can
        reference elements by index. This keeps the live view the user watches clean and readable."""
        clean = await self._shot()                       # user-facing (no marks)
        elements: list[dict] = []
        for attempt in (1, 2):
            try:
                elements = await self.page.evaluate(_MARK_JS)
                break
            except Exception as exc:
                # "Execution context was destroyed" means the page navigated mid-perceive — let it
                # settle and retry once before giving up (empty list → the agent scrolls/waits).
                if attempt == 1:
                    log.warning("ipa_mark_retry", error=str(exc), error_type=type(exc).__name__)
                    try:
                        await self.page.wait_for_load_state("domcontentloaded", timeout=4000)
                    except Exception:
                        await self.page.wait_for_timeout(700)
                    continue
                log.warning("ipa_mark_failed", error=str(exc), error_type=type(exc).__name__)
        marked = await self._shot()                      # agent-facing (index boxes drawn)
        try:
            url, title = self.page.url, await self.page.title()
        except Exception:
            url, title = "", ""
        try:
            await self.page.evaluate(_CLEAR_JS)
        except Exception:
            pass
        log.debug("ipa_perceive", url=(url or "")[:120], title=(title or "")[:80],
                  elements=len(elements))
        return clean, marked, elements, url, title

    async def _sel(self, index: int) -> str:
        return f'[data-ipa-index="{index}"]'

    async def act(self, action_type: str, index: int | None, text: str) -> str:
        """Perform one action on the page. Returns a short human-readable outcome string."""
        log.debug("ipa_act", action=action_type, index=index, url=self.current_url)
        try:
            if action_type == "navigate":
                await self.goto(text)
                return f"navigated to {text}"
            if action_type == "scroll":
                await self.page.mouse.wheel(0, 700)
                await self.page.wait_for_timeout(300)
                return "scrolled down"
            if action_type == "wait":
                await self.page.wait_for_timeout(1200)
                return "waited"
            if action_type == "press":
                # Press a keyboard key — chiefly Enter to submit a search box that has no visible
                # Search button ("Press Enter to search"). Focus the target field first if given,
                # so Enter submits THAT field's form; else press on whatever currently has focus.
                key = (text or "Enter").strip() or "Enter"
                if index is not None:
                    sel = await self._sel(index)
                    await self.page.press(sel, key)
                else:
                    await self.page.keyboard.press(key)
                await self.page.wait_for_timeout(700)
                return f"pressed {key}"
            if index is None:
                return "no target element"
            sel = await self._sel(index)
            if action_type == "type":
                await self.page.fill(sel, text)
                return f"typed '{text}' into #{index}"
            if action_type == "select":
                try:
                    await self.page.select_option(sel, label=text)
                except Exception:
                    await self.page.select_option(sel, value=text)
                return f"selected '{text}' in #{index}"
            if action_type == "click":
                await self.page.click(sel)
                await self.page.wait_for_timeout(600)
                return f"clicked #{index}"
        except Exception as exc:
            log.warning("ipa_act_failed", action=action_type, index=index,
                        error=str(exc), error_type=type(exc).__name__)
            return f"action failed: {str(exc)[:120]}"
        return f"unknown action {action_type}"

    # ── User remote-control (during a hand-off the user drives the SAME server browser) ────
    async def user_click(self, x: float, y: float) -> None:
        try:
            await self.page.mouse.click(float(x), float(y))
            await self.page.wait_for_timeout(200)
        except Exception as exc:
            log.debug("user_click_failed", error=str(exc), error_type=type(exc).__name__)

    async def user_type(self, text: str) -> None:
        try:
            await self.page.keyboard.type(str(text), delay=15)
        except Exception as exc:
            log.debug("user_type_failed", error=str(exc), error_type=type(exc).__name__)

    async def user_key(self, key: str) -> None:
        try:
            await self.page.keyboard.press(str(key))
            await self.page.wait_for_timeout(150)
        except Exception as exc:
            log.debug("user_key_failed", error=str(exc), error_type=type(exc).__name__)

    async def user_scroll(self, dy: float) -> None:
        try:
            await self.page.mouse.wheel(0, float(dy))
        except Exception as exc:
            log.debug("user_scroll_failed", error=str(exc), error_type=type(exc).__name__)

    async def clean_shot(self) -> str:
        """A user-facing screenshot (no marks) — used to refresh the live view during hand-off."""
        return await self._shot()

    @property
    def current_url(self) -> str:
        try:
            return self.page.url if self.page else ""
        except Exception:
            return ""

    async def close(self) -> None:
        log.info("ipa_browser_closing", url=self.current_url)
        for closer in (self._context, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception as exc:
                log.debug("ipa_browser_close_error", error=str(exc), error_type=type(exc).__name__)
        try:
            if self._pw:
                await self._pw.stop()
        except Exception as exc:
            log.debug("ipa_playwright_stop_error", error=str(exc), error_type=type(exc).__name__)
        log.info("ipa_browser_closed")
