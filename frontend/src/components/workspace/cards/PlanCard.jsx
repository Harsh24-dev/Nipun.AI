import React from "react";

export default function PlanCard({ card }) {
  const cols = card.planCols || [];
  const rows = card.planRows || [];
  const steps = card.steps || [];

  // A plan can arrive as a table (planCols/planRows) OR as a list of steps
  // (task/plan previews). When there's no table, render the steps + summary so the
  // card never shows as an empty grid.
  if (rows.length === 0) {
    return (
      <div>
        {card.title && <h3 className="font-semibold text-sm mb-3">{card.title}</h3>}
        {(card.summary || card.plan?.description) && (
          <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>{card.summary || card.plan?.description}</p>
        )}
        <div className="space-y-2">
          {steps.map((s, i) => (
            <div key={i} className="flex items-start gap-3 p-3 rounded-lg" style={{ background: "var(--surface-sunken)" }}>
              <span className="text-xs font-mono px-1.5 py-0.5 rounded flex-shrink-0" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>{i + 1}</span>
              <div className="min-w-0">
                <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{s.title || s.label}</p>
                {(s.desc || s.description) && <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{s.desc || s.description}</p>}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {card.title && <h3 className="font-semibold text-sm mb-3">{card.title}</h3>}
      {(card.summary || card.plan?.description) && <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>{card.summary || card.plan?.description}</p>}
      <div className="overflow-x-auto rounded-lg border" style={{ borderColor: "var(--border)" }}>
        <table className="w-full text-xs">
          <thead>
            <tr style={{ background: "var(--surface-sunken)" }}>
              {cols.map((col, i) => (
                <th key={i} className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)", borderBottom: "1px solid var(--border)" }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: i < rows.length - 1 ? "1px solid var(--border-subtle)" : "none" }}>
                {cols.map((col, j) => (
                  <td key={j} className="px-3 py-2" style={{ color: "var(--text)" }}>
                    {row[col] ?? "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}