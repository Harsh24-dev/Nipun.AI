import React from "react";
import { CloudSun, AlertTriangle } from "lucide-react";
import { CardTitle, Prose, TextFallback } from "@/components/workspace/cards/_shared";

export default function WeatherCard({ card }) {
  const w = card.weather;
  // No structured weather payload → don't render an empty box; show the text answer.
  if (!w) return <TextFallback card={card} />;

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="p-4 rounded-xl mt-3" style={{ background: "var(--surface-sunken)" }}>
        <div className="flex items-center gap-4 mb-4">
          <CloudSun size={36} style={{ color: "var(--accent)" }} />
          <div>
            {/* temp already carries its unit from the backend (e.g. "32°C"). */}
            <span className="text-3xl font-bold" style={{ color: "var(--text)" }}>{w.temp}</span>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{w.condition}</p>
          </div>
        </div>
        {w.forecast && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {w.forecast.map((f, i) => (
              <div key={i} className="flex flex-col items-center p-2 rounded-lg min-w-[60px]" style={{ background: "var(--surface)" }}>
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{f.day || f.date}</span>
                <span className="text-sm font-semibold mt-1" style={{ color: "var(--text)" }}>{f.temp}</span>
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{f.condition}</span>
              </div>
            ))}
          </div>
        )}
        {w.alerts && w.alerts.length > 0 && (
          <div className="mt-3 p-2 rounded-lg flex items-center gap-2" style={{ background: "rgba(217,119,6,0.1)" }}>
            <AlertTriangle size={14} style={{ color: "var(--warning)" }} />
            <span className="text-xs" style={{ color: "var(--warning)" }}>{w.alerts[0]}</span>
          </div>
        )}
      </div>
    </div>
  );
}