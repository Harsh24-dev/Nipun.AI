import React from "react";
import { AlertCircle } from "lucide-react";

export default function ErrorCard({ card }) {
  return (
    <div className="flex items-start gap-3 p-4 rounded-lg" style={{ background: "rgba(220,38,38,0.06)" }}>
      <AlertCircle size={18} className="flex-shrink-0 mt-0.5" style={{ color: "var(--destructive)" }} />
      <div>
        <p className="text-sm" style={{ color: "var(--text)" }}>{card.summary || card.title || "An error occurred"}</p>
        {card.correlationId && (
          <p className="text-[10px] mt-1 font-mono" style={{ color: "var(--text-muted)" }}>ID: {card.correlationId}</p>
        )}
      </div>
    </div>
  );
}