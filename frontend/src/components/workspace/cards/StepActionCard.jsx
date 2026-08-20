import React, { useState } from "react";
import { CheckCircle, Circle, Clock, ExternalLink, Check, X, ClipboardList, AlertCircle } from "lucide-react";
import { CardTitle, Prose } from "@/components/workspace/cards/_shared";
import { tasks as tasksApi } from "@/lib/api";

// The task card: shows the plan/steps AND the concrete work an assistant prepared — the
// filled field values, what's still needed, a link to open the portal, and (when present)
// a confirm/reject action for a prepared task.
export default function StepActionCard({ card }) {
  const fields = card.filledForm?.fields || [];
  const missing = card.missingFields || [];
  const portal = card.portal;
  const confirmation = card.confirmation;

  const [confirmState, setConfirmState] = useState(null); // null | "confirming" | "confirmed" | "rejected" | "error"
  const [confirmMsg, setConfirmMsg] = useState("");

  const act = async (kind) => {
    if (!confirmation?.token) return;
    setConfirmState(kind === "confirm" ? "confirming" : "rejected");
    try {
      if (kind === "confirm") {
        const res = await tasksApi.confirm({ token: confirmation.token });
        setConfirmState("confirmed");
        setConfirmMsg(res?.message || "Confirmed.");
      } else {
        await tasksApi.reject({ token: confirmation.token });
        setConfirmMsg("Cancelled.");
      }
    } catch (e) {
      setConfirmState("error");
      setConfirmMsg(e?.message || "Something went wrong.");
    }
  };

  return (
    <div className="space-y-2">
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>

      {/* Prepared field values — the work Nipun filled in for the user to review */}
      {fields.length > 0 && (
        <div className="rounded-lg p-3 mt-1" style={{ background: "var(--surface-sunken)" }}>
          <div className="flex items-center gap-1.5 mb-2">
            <ClipboardList size={12} style={{ color: "var(--accent)" }} />
            <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Prepared for you — review before submitting
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
            {fields.map((f, i) => (
              <div key={i} className="flex justify-between gap-2 text-xs py-0.5">
                <span style={{ color: "var(--text-muted)" }}>{f.label}</span>
                <span className="font-medium text-right" style={{ color: "var(--text)" }}>{String(f.value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Still needed from the user */}
      {missing.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg p-2.5 text-xs" style={{ background: "var(--surface-sunken)" }}>
          <AlertCircle size={13} className="mt-0.5 flex-shrink-0" style={{ color: "var(--warning)" }} />
          <span style={{ color: "var(--text-secondary)" }}>
            Still needed: <span style={{ color: "var(--text)", fontWeight: 500 }}>{missing.join(", ")}</span>
          </span>
        </div>
      )}

      {/* Open the portal / site */}
      {portal?.url && (
        <a href={portal.url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm hover:opacity-80"
          style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
          <ExternalLink size={14} /> Open {portal.name || "the site"}
        </a>
      )}

      {(card.steps || []).map((step, i) => (
        <div key={i} className="flex items-start gap-3 p-3 rounded-lg" style={{ background: "var(--surface-sunken)" }}>
          <div className="flex-shrink-0 mt-0.5">
            {step.status === "done" ? (
              <CheckCircle size={18} style={{ color: "var(--success)" }} />
            ) : (
              <Circle size={18} style={{ color: "var(--text-muted)" }} />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
                {i + 1}
              </span>
              <span className="text-sm font-medium" style={{ color: "var(--text)" }}>{step.title}</span>
            </div>
            {step.desc && <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{step.desc}</p>}
            {step.duration && (
              <span className="inline-flex items-center gap-1 text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>
                <Clock size={10} /> {step.duration}
              </span>
            )}
          </div>
        </div>
      ))}

      {/* Confirm / cancel a prepared action */}
      {confirmation?.token && confirmState !== "confirmed" && confirmState !== "rejected" && (
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => act("confirm")} disabled={confirmState === "confirming"}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-60"
            style={{ background: "var(--accent)", color: "#fff" }}>
            <Check size={14} /> {confirmState === "confirming" ? "Confirming…" : "Confirm"}
          </button>
          <button onClick={() => act("reject")}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm hover:opacity-80"
            style={{ background: "var(--surface-sunken)", color: "var(--text-muted)" }}>
            <X size={14} /> Cancel
          </button>
        </div>
      )}
      {confirmMsg && (
        <p className="text-xs pt-1" style={{ color: confirmState === "error" ? "var(--destructive)" : "var(--text-muted)" }}>
          {confirmMsg}
        </p>
      )}
    </div>
  );
}
