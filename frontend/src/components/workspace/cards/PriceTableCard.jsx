import React from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { CardTitle, Prose } from "@/components/workspace/cards/_shared";

// The backend PriceItem sends `change` as the direction "up"/"down"/"flat" and `rate`
// as the percentage text (e.g. "+2.3%"). Older/other producers may send a numeric
// `change`. Normalize both into a direction + optional display value.
function normalizeChange(change, rate) {
  if (typeof change === "number") {
    return { dir: change > 0 ? "up" : change < 0 ? "down" : "flat", text: rate || `${change > 0 ? "+" : ""}${change}%` };
  }
  const s = String(change ?? "").toLowerCase();
  if (s === "up" || s === "down" || s === "flat") return { dir: s, text: rate || "" };
  const n = parseFloat(s);
  if (!Number.isNaN(n)) return { dir: n > 0 ? "up" : n < 0 ? "down" : "flat", text: rate || s };
  return null;
}

export default function PriceTableCard({ card }) {
  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="space-y-2 mt-3">
        {(card.prices || []).map((p, i) => {
          const c = normalizeChange(p.change, p.rate);
          const color = c?.dir === "up" ? "var(--success)" : c?.dir === "down" ? "var(--destructive)" : "var(--text-muted)";
          const Icon = c?.dir === "up" ? TrendingUp : c?.dir === "down" ? TrendingDown : Minus;
          return (
            <div key={i} className="flex items-center justify-between p-3 rounded-lg" style={{ background: "var(--surface-sunken)" }}>
              <div>
                <span className="text-sm font-medium" style={{ color: "var(--text)" }}>{p.crop || p.name}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>{p.price}</span>
                {c && (
                  <span className="flex items-center gap-0.5 text-xs" style={{ color }}>
                    <Icon size={12} />
                    {c.text}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
