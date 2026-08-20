import React from "react";
import { CheckCircle, XCircle, ExternalLink } from "lucide-react";
import { CardTitle, Prose } from "@/components/workspace/cards/_shared";

export default function SchemeListCard({ card }) {
  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="space-y-2 mt-3">
        {(card.schemes || []).map((s, i) => (
          <div key={i} className="p-3 rounded-lg border" style={{ background: "var(--surface-sunken)", borderColor: "var(--border-subtle)" }}>
            <div className="flex items-start justify-between mb-1">
              <span className="text-sm font-medium" style={{ color: "var(--text)" }}>{s.name}</span>
              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full"
                style={{ background: s.eligible ? "rgba(22,163,74,0.1)" : "rgba(220,38,38,0.1)", color: s.eligible ? "var(--success)" : "var(--destructive)" }}>
                {s.eligible ? <CheckCircle size={10} /> : <XCircle size={10} />}
                {s.eligible ? "Eligible" : "Not eligible"}
              </span>
            </div>
            {s.benefit && <p className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>{s.benefit}</p>}
            {s.criteria && <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Criteria: {s.criteria}</p>}
            {s.link && (
              <a href={s.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[10px] mt-1 hover:underline" style={{ color: "var(--accent)" }}>
                Learn more <ExternalLink size={8} />
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}