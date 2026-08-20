import React from "react";
import { Bot, Play, ShieldCheck, Globe, MousePointerClick } from "lucide-react";
import { Prose } from "@/components/workspace/cards/_shared";
import { startTask } from "@/components/task/TaskRunnerHost";

// The task launcher shown in chat when the user asks the agent to DO something. Clicking Start
// opens the live runner: one form for the details, then real browser execution the user watches.
export default function AgentTaskCard({ card }) {
  const goal = card.goal || card.title || "";
  return (
    <div className="rounded-xl p-3.5 border" style={{
      borderColor: "var(--accent)",
      background: "linear-gradient(135deg, rgba(37,99,235,0.06), rgba(124,58,237,0.06))",
    }}>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="h-7 w-7 rounded-lg flex items-center justify-center" style={{ background: "var(--accent)" }}>
          <Bot size={16} style={{ color: "#fff" }} />
        </span>
        <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>I can do this for you</span>
      </div>
      <Prose>{card.summary}</Prose>
      <div className="flex items-center gap-3 mt-3 flex-wrap">
        <button
          onClick={() => startTask(goal)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold shadow-sm transition-transform hover:-translate-y-0.5"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          <Play size={15} /> Start — run it for me
        </button>
      </div>
      <div className="flex items-center gap-3 mt-2.5 flex-wrap text-[11px]" style={{ color: "var(--text-muted)" }}>
        <span className="inline-flex items-center gap-1"><Globe size={12} /> Watch it live</span>
        <span className="inline-flex items-center gap-1"><MousePointerClick size={12} /> Take over anytime</span>
        <span className="inline-flex items-center gap-1"><ShieldCheck size={12} /> Pauses for login / OTP / payment</span>
      </div>
    </div>
  );
}
