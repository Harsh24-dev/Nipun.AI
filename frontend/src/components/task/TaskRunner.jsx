import React, { useEffect, useRef, useState, useCallback } from "react";
import { X, Bot, Loader2, CheckCircle2, AlertTriangle, ShieldCheck, Hand, ExternalLink } from "lucide-react";
import { taskAgent, createTaskWebSocket, getToken } from "@/lib/api";
import BrowserView from "./BrowserView";
import ChecklistPanel from "./ChecklistPanel";
import TaskControls from "./TaskControls";
import OptionsPanel from "./OptionsPanel";

// Colour-coded run status shown in the header chip.
const STATUS_UI = {
  planning: { label: "Planning", color: "var(--text-muted)" },
  awaiting_input: { label: "Your details", color: "var(--accent)" },
  comparing: { label: "Comparing", color: "#7c3aed" },
  awaiting_choice: { label: "Choose one", color: "#d97706" },
  running: { label: "Running", color: "var(--accent)" },
  paused: { label: "Paused", color: "#d97706" },
  needs_human: { label: "Needs you", color: "#d97706" },
  done: { label: "Done", color: "#16a34a" },
  failed: { label: "Failed", color: "#dc2626" },
  stopped: { label: "Stopped", color: "var(--text-muted)" },
};

// The IPA task runner: plan → one consolidated form → live browser execution with human-in-loop.
// Mounted once (TaskRunnerHost) and opened with a goal. Owns the task WebSocket lifecycle.
export default function TaskRunner({ goal, onClose }) {
  const [phase, setPhase] = useState("planning");        // planning | form | running
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState(null);
  const [plan, setPlan] = useState(null);
  const [answers, setAnswers] = useState({});
  const [steps, setSteps] = useState([]);
  const [status, setStatus] = useState("planning");
  const [view, setView] = useState({ screenshot: "", url: "", title: "" });
  const [action, setAction] = useState("");
  const [notice, setNotice] = useState("");
  const [logs, setLogs] = useState([]);
  const [options, setOptions] = useState([]);
  const [resultUrl, setResultUrl] = useState("");
  const wsRef = useRef(null);
  const surface = plan?.surface || "web";

  // Apply a safe in-app action the agent decided (theme / navigation / open link). Profile and
  // other settings are also persisted server-side by the backend and reflect on next load.
  const applyAppAction = useCallback((a) => {
    if (!a) return;
    try {
      if (a.type === "set_setting" && a.key === "theme" && a.value) {
        document.documentElement.setAttribute("data-theme", a.value);
      } else if (a.type === "open_url" && a.url) {
        window.open(a.url, "_blank", "noopener");
      } else if (a.type === "navigate" && a.path) {
        setTimeout(() => window.location.assign(a.path), 800);
      }
    } catch {}
  }, []);

  // 1) Plan the task.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await taskAgent.start(goal);
        if (!alive) return;
        setTaskId(res.task_id);
        setPlan(res.plan);
        setSteps(res.plan?.steps || []);
        // Pre-seed the form from any known values (none yet).
        const init = {};
        (res.plan?.form_fields || []).forEach((f) => { init[f.name] = ""; });
        setAnswers(init);
        // Only show the form when the agent actually needs details. If there are no
        // fields, skip straight to running the task.
        if (res.plan?.form_fields?.length) {
          setPhase("form");
        } else {
          startRun(res.task_id);
        }
      } catch (e) {
        setError("Could not plan this task. Please try again.");
      }
    })();
    return () => { alive = false; };
  }, [goal]);

  const send = useCallback((obj) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(obj));
  }, []);

  const chooseOption = useCallback((o) => {
    send({ action: "choose_option", data: o });
    setOptions([]);
    setStatus("running");
    setNotice(`Proceeding on ${o.provider || o.name || "your choice"}…`);
  }, [send]);

  // 3) Open the live WS and stream the run.
  const startRun = useCallback((tid = taskId) => {
    if (!tid) return;
    setPhase("running");
    setStatus("running");
    const ws = createTaskWebSocket(tid);
    wsRef.current = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ token: getToken() }));
      ws.send(JSON.stringify({ action: "answers", data: answers }));
    };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      switch (m.type) {
        case "status": setStatus(m.status); break;
        case "step":
          setSteps((prev) => prev.map((s) => (s.id === m.step_id ? { ...s, status: m.status } : s)));
          break;
        case "screenshot":
          setView({ screenshot: m.image, url: m.url, title: m.title });
          break;
        case "action":
          setAction(m.thought || m.outcome || "");
          setLogs((l) => [...l.slice(-40), { t: m.thought, o: m.outcome }]);
          break;
        case "app_action":
          applyAppAction(m.action);
          setLogs((l) => [...l.slice(-40), { t: `Applied: ${m.action?.type} ${m.action?.key || m.action?.path || m.action?.field || ""}`, o: "" }]);
          break;
        case "options": setOptions(m.options || []); setStatus("awaiting_choice"); setNotice(m.note || ""); break;
        case "message": setNotice(m.text); setLogs((l) => [...l.slice(-40), { t: m.text, o: "" }]); break;
        case "needs_human":
          setStatus("needs_human"); setNotice(m.instruction || m.reason || "Your help is needed."); break;
        case "done":
          setStatus(m.status || (m.success ? "done" : "failed"));
          setAction("");
          // The final page URL (web tasks only) — lets the user reopen the result/confirmation
          // page in their own browser. Only trust a real http(s) URL.
          if (typeof m.url === "string" && /^https?:\/\//i.test(m.url)) setResultUrl(m.url);
          break;
        case "error":
          setError(m.message || "Something went wrong."); setStatus("failed"); break;
        default: break;
      }
    };
    ws.onerror = () => setError("Connection error.");
    ws.onclose = () => { wsRef.current = null; };
  }, [taskId, answers]);

  useEffect(() => () => { try { wsRef.current?.close(); } catch {} }, []);
  // Esc closes the modal (a11y / expected modal behaviour).
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const [mounted, setMounted] = useState(false);
  useEffect(() => { const t = setTimeout(() => setMounted(true), 10); return () => clearTimeout(t); }, []);

  const fields = plan?.form_fields || [];
  const missing = fields.some((f) => f.required && !String(answers[f.name] || "").trim());
  const st = STATUS_UI[status] || STATUS_UI.planning;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3"
      style={{ background: "rgba(0,0,0,0.55)", opacity: mounted ? 1 : 0, transition: "opacity .2s ease" }}
      onClick={onClose}>
      <div className="w-full max-w-[1600px] max-h-[94vh] overflow-hidden rounded-xl border flex flex-col"
        style={{ background: "var(--background)", borderColor: "var(--border)",
                 opacity: mounted ? 1 : 0, transform: mounted ? "scale(1)" : "scale(0.97)",
                 transition: "opacity .2s ease, transform .2s ease" }}
        onClick={(e) => e.stopPropagation()}>
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: "var(--border-subtle)" }}>
          <div className="flex items-center gap-2 min-w-0">
            <Bot size={18} style={{ color: "var(--accent)" }} />
            <div className="min-w-0">
              <div className="text-sm font-semibold truncate" style={{ color: "var(--text)" }}>Agent task</div>
              <div className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>{goal}</div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-full"
              style={{ background: `${st.color}1e`, color: st.color }}>
              <span className="h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: st.color }} />
              {st.label}
            </span>
            <button onClick={onClose} className="p-1 rounded hover:opacity-70" style={{ color: "var(--text-muted)" }}>
              <X size={18} />
            </button>
          </div>
        </div>

        {error && (
          <div className="mx-4 mt-3 px-3 py-2 rounded-md text-xs flex items-center gap-2"
            style={{ background: "var(--surface-sunken)", color: "var(--destructive)" }}>
            <AlertTriangle size={13} /> {error}
          </div>
        )}

        {/* PLANNING */}
        {phase === "planning" && (
          <div className="flex items-center justify-center gap-2 py-24 text-sm" style={{ color: "var(--text-muted)" }}>
            <Loader2 size={16} className="animate-spin" /> Planning the task…
          </div>
        )}

        {/* FORM — one consolidated form, then start */}
        {phase === "form" && plan && (
          <div className="overflow-y-auto p-4 space-y-4 flex-1 min-h-0">
            {plan.summary && <p className="text-sm" style={{ color: "var(--text)" }}>{plan.summary}</p>}
            {plan.target?.name && surface === "web" && (
              <div className="text-xs flex items-start gap-1.5" style={{ color: "var(--text-muted)" }}>
                <ShieldCheck size={13} style={{ marginTop: 1, flexShrink: 0, color: "var(--success)" }} />
                <span>Using <span style={{ color: "var(--text)", fontWeight: 500 }}>{plan.target.name}</span>
                  {plan.target.why ? ` — ${plan.target.why}` : ""}. I'll compare the best trusted options before proceeding.</span>
              </div>
            )}
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>Checklist</div>
              <ChecklistPanel steps={steps} />
            </div>
            {fields.length > 0 && (
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                  Details the agent needs
                </div>
                <div className="grid sm:grid-cols-2 gap-3">
                  {fields.map((f) => (
                    <label key={f.name} className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      {f.label}{f.required && <span style={{ color: "var(--destructive)" }}> *</span>}
                      {f.type === "select" ? (
                        <select value={answers[f.name] || ""} onChange={(e) => setAnswers((a) => ({ ...a, [f.name]: e.target.value }))}
                          className="mt-1 w-full px-2 py-1.5 rounded-md border text-sm"
                          style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}>
                          <option value="">Select…</option>
                          {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      ) : (
                        <input type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}
                          value={answers[f.name] || ""} placeholder={f.placeholder || ""}
                          onChange={(e) => setAnswers((a) => ({ ...a, [f.name]: e.target.value }))}
                          className="mt-1 w-full px-2 py-1.5 rounded-md border text-sm"
                          style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
                      )}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="flex items-center gap-2 pt-1">
              <button onClick={() => startRun()} disabled={missing}
                className="px-4 py-2 rounded-md text-sm font-medium disabled:opacity-50"
                style={{ background: "var(--accent)", color: "#fff" }}>
                Start — run it for me
              </button>
              <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                The agent pauses at login / OTP / payment for you to complete.
              </span>
            </div>
          </div>
        )}

        {/* RUNNING — live browser + checklist. Column layout: the content area scrolls INTERNALLY
            while the hand-off / controls bar stays PINNED at the bottom, always visible. */}
        {phase === "running" && (
          <div className="flex flex-col flex-1 min-h-0">
            <div className="grid md:grid-cols-[1fr_280px] gap-3 p-4 overflow-y-auto flex-1 min-h-0">
              <div className="space-y-2 min-w-0">
                {/* Prominent hand-off panel: when the agent hands control back (login / OTP / blocked
                    embedded page), make the human step effortless and unmistakable. */}
                {status === "needs_human" && (
                  <div className="rounded-lg border px-3 py-2.5" role="alert"
                    style={{ borderColor: "var(--warning)", background: "color-mix(in srgb, var(--warning) 12%, transparent)" }}>
                    <div className="flex items-start gap-2">
                      <Hand size={16} style={{ color: "var(--warning)", marginTop: 1, flexShrink: 0 }} />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold" style={{ color: "var(--text)" }}>This step needs you</div>
                        <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                          {notice || "Sign in / enter your OTP in the view below — I never handle passwords or codes — then tap “I've done it — continue”."}
                        </div>
                        {surface === "web" && view.url && (
                          <button onClick={() => window.open(view.url, "_blank", "noopener")}
                            className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-md border"
                            style={{ borderColor: "var(--border)", color: "var(--text)", background: "var(--surface)" }}>
                            <ExternalLink size={12} /> Open the real page in a new tab
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )}
                {status === "awaiting_choice" && options.length > 0 ? (
                  <OptionsPanel options={options} note={notice} onChoose={chooseOption} />
                ) : surface === "web" ? (
                  <BrowserView screenshot={view.screenshot} url={view.url} title={view.title} action={action}
                    interactive={["needs_human", "paused"].includes(status)} onInteract={send} />
                ) : (
                  <div className="rounded-lg border p-4" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                    <div className="text-xs font-medium mb-2" style={{ color: "var(--text-muted)" }}>
                      {surface === "app" ? "Applying changes in the app" : "Working in the sandbox"}
                    </div>
                    <div className="space-y-1 max-h-72 overflow-y-auto text-xs" style={{ color: "var(--text-secondary)" }}>
                      {logs.length === 0 && <div style={{ color: "var(--text-muted)" }}>Starting…</div>}
                      {logs.map((l, i) => (
                        <div key={i} className="break-words">{l.t}{l.o ? <span style={{ color: "var(--text-muted)" }}> — {l.o}</span> : null}</div>
                      ))}
                    </div>
                  </div>
                )}
                {/* Non-critical status notice (running / comparing). The needs_human case is covered
                    by the panel above, so it is excluded here to avoid a duplicate message. */}
                {notice && !["awaiting_choice", "needs_human"].includes(status) && (
                  <div className="px-3 py-2 rounded-md text-xs flex items-center gap-2"
                    style={{ background: "var(--surface-sunken)", color: "var(--text-secondary)" }}>
                    <Loader2 size={13} className="animate-spin flex-shrink-0" />
                    <span className="break-words">{notice}</span>
                  </div>
                )}
                {status === "done" && (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
                    <span className="flex items-center gap-1.5" style={{ color: "var(--success)" }}>
                      <CheckCircle2 size={15} className="flex-shrink-0" /> Task finished. Review the result above.
                    </span>
                    {resultUrl && (
                      <a href={resultUrl} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border hover:opacity-80"
                        style={{ borderColor: "var(--border)", color: "var(--accent)", background: "var(--surface)" }}>
                        <ExternalLink size={12} /> Open the result page
                      </a>
                    )}
                  </div>
                )}
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>Progress</div>
                <ChecklistPanel steps={steps} />
              </div>
            </div>
            {/* Pinned action bar — hand-off / pause / stop stays visible regardless of scroll. */}
            {!["done", "failed", "stopped"].includes(status) && (
              <div className="flex items-center justify-between gap-3 px-4 py-3 border-t flex-shrink-0 flex-wrap"
                style={{ borderColor: "var(--border-subtle)", background: "var(--surface-sunken)" }}>
                <TaskControls status={status}
                  onPause={() => send({ action: "pause" })}
                  onResume={() => send({ action: "resume" })}
                  onStop={() => send({ action: "stop" })}
                  onHumanDone={() => { send({ action: "human_done" }); setStatus("running"); setNotice(""); }} />
                <span className="text-[11px] hidden sm:block" style={{ color: "var(--text-muted)" }}>
                  I pause at login / OTP / payment for you.
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
