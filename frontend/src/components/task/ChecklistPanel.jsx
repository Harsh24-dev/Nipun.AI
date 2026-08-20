import React from "react";
import { Check, Loader2, Hand, X, Circle, AlertTriangle } from "lucide-react";
import { Reveal } from "@/components/workspace/cards/RichBlocks";

const STATE = {
  done: { Icon: Check, color: "#16a34a" },
  running: { Icon: Loader2, color: "var(--accent)", spin: true },
  needs_human: { Icon: Hand, color: "#d97706" },
  failed: { Icon: X, color: "#dc2626" },
  skipped: { Icon: Circle, color: "var(--text-muted)" },
  pending: { Icon: Circle, color: "var(--text-muted)" },
};

// The live task checklist: an overall progress bar, a connecting spine, and colour-coded steps
// with an animated entrance and an active-step highlight — so the user can follow and verify.
export default function ChecklistPanel({ steps }) {
  if (!steps?.length) return null;
  const done = steps.filter((s) => s.status === "done").length;
  const pct = Math.round((done / steps.length) * 100);

  return (
    <div>
      {/* progress bar */}
      <div className="flex items-center gap-2 mb-2.5">
        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--surface-sunken)" }}>
          <div className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pct}%`, background: pct === 100 ? "#16a34a" : "var(--accent)" }} />
        </div>
        <span className="text-[11px] font-semibold tabular-nums" style={{ color: "var(--text-muted)" }}>
          {done}/{steps.length}
        </span>
      </div>

      <div className="relative">
        {/* connecting spine */}
        <div className="absolute left-[9px] top-2 bottom-2 w-px" style={{ background: "var(--border-subtle)" }} />
        <div className="space-y-1">
          {steps.map((s, i) => {
            const conf = STATE[s.status] || STATE.pending;
            const { Icon } = conf;
            const active = s.status === "running" || s.status === "needs_human";
            return (
              <Reveal key={s.id} delay={i * 40}
                className="relative flex items-start gap-2.5 rounded-lg px-2 py-1.5 transition-colors"
                style={{ background: active ? `${conf.color}14` : "transparent" }}>
                <span className="relative z-10 flex-shrink-0 h-[19px] w-[19px] rounded-full flex items-center justify-center"
                  style={{ background: "var(--background)", border: `2px solid ${conf.color}` }}>
                  <Icon size={11} className={conf.spin ? "animate-spin" : ""} style={{ color: conf.color }} />
                </span>
                <div className="min-w-0 pt-0.5">
                  <div className="text-sm leading-snug flex items-center gap-1.5 flex-wrap"
                    style={{ color: active ? "var(--text)" : (s.status === "done" ? "var(--text-secondary)" : "var(--text)"),
                             fontWeight: active ? 600 : 400 }}>
                    {s.title}
                    {s.sensitive && (
                      <span className="inline-flex items-center gap-0.5 text-[10px] px-1 rounded"
                        style={{ background: "#d9770622", color: "#d97706" }}>
                        <AlertTriangle size={9} /> you
                      </span>
                    )}
                  </div>
                  {s.detail && active && (
                    <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>{s.detail}</div>
                  )}
                </div>
              </Reveal>
            );
          })}
        </div>
      </div>
    </div>
  );
}
