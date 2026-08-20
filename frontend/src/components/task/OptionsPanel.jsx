import React from "react";
import { Star, ShieldCheck, Check, Trophy } from "lucide-react";
import { Reveal, PALETTE } from "@/components/workspace/cards/RichBlocks";

// The few best options the agent compared across trusted sources. The user picks one; the agent
// then executes on that choice. Only reputable sources reach here (backend trust gate).
export default function OptionsPanel({ options, note, onChoose }) {
  return (
    <div className="space-y-2">
      <div className="text-xs flex items-center gap-1.5" style={{ color: "var(--text-muted)" }}>
        <ShieldCheck size={13} style={{ color: "#16a34a" }} />
        {note || "Best options from trusted sources — pick one to proceed."}
      </div>
      {options.map((o, i) => {
        const c = PALETTE[i % PALETTE.length];
        return (
        <Reveal key={i} delay={i * 70} className="rounded-lg border p-3 pl-4 relative overflow-hidden transition-transform hover:-translate-y-0.5"
          style={{ borderColor: i === 0 ? c.fg : "var(--border)", background: "var(--surface)" }}>
          <span className="absolute left-0 top-0 bottom-0 w-1" style={{ background: c.fg }} />
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              {i === 0 && (
                <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full mb-1"
                  style={{ background: `${c.fg}1e`, color: c.fg }}><Trophy size={10} /> Best pick</span>
              )}
              <div className="text-sm font-medium" style={{ color: "var(--text)" }}>{o.name || o.provider}</div>
              {o.provider && <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{o.provider}</div>}
            </div>
            <div className="text-right flex-shrink-0">
              {o.price && <div className="text-sm font-semibold whitespace-nowrap" style={{ color: "var(--text)" }}>{o.price}</div>}
              {o.rating && (
                <div className="text-[11px] flex items-center gap-0.5 justify-end" style={{ color: "var(--text-muted)" }}>
                  <Star size={10} /> {o.rating}
                </div>
              )}
            </div>
          </div>
          {o.why && <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{o.why}</div>}
          {(o.pros?.length > 0 || o.cons?.length > 0) && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {(o.pros || []).map((p, j) => (
                <span key={`p${j}`} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface-sunken)", color: "var(--success)" }}>+ {p}</span>
              ))}
              {(o.cons || []).map((c, j) => (
                <span key={`c${j}`} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface-sunken)", color: "var(--text-muted)" }}>– {c}</span>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between mt-2">
            <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
              style={{ background: "var(--surface-sunken)", color: o.reliability === "high" ? "var(--success)" : "var(--text-muted)" }}>
              <ShieldCheck size={10} /> {o.reliability} reliability
            </span>
            <button onClick={() => onChoose(o)}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-md text-xs font-medium"
              style={{ background: "var(--accent)", color: "#fff" }}>
              <Check size={12} /> Choose
            </button>
          </div>
        </Reveal>
        );
      })}
    </div>
  );
}
