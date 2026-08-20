import React, { useEffect, useState } from "react";
import { Lightbulb, Info, AlertTriangle, CheckCircle2, Star, Copy, Check } from "lucide-react";

// Rich, colourful, interactive answer blocks the synthesis agent places inline (key-points,
// callouts, stat tiles, colour swatches). Deliberately uses a MULTI-COLOUR palette — not just the
// app theme — so responses are lively and easy to scan, in both light and dark mode.

export const PALETTE = [
  { fg: "#2563eb", bg: "rgba(37,99,235,0.12)" },   // blue
  { fg: "#16a34a", bg: "rgba(22,163,74,0.12)" },   // green
  { fg: "#db2777", bg: "rgba(219,39,119,0.12)" },  // pink
  { fg: "#d97706", bg: "rgba(217,119,6,0.12)" },   // amber
  { fg: "#7c3aed", bg: "rgba(124,58,237,0.12)" },  // violet
  { fg: "#0891b2", bg: "rgba(8,145,178,0.12)" },   // cyan
];

// Fade-up-on-mount wrapper — gives blocks a gentle, staggered entrance (dynamic, not static).
export function Reveal({ children, delay = 0, className = "", style = {} }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(t);
  }, [delay]);
  return (
    <div className={className} style={{
      ...style, opacity: shown ? 1 : 0, transform: shown ? "none" : "translateY(6px)",
      transition: "opacity .35s ease, transform .35s ease",
    }}>{children}</div>
  );
}

export function KeyPointsCard({ card }) {
  const items = card.items || [];
  if (!items.length) return null;
  return (
    <div className="grid sm:grid-cols-2 gap-2 my-1">
      {items.map((it, i) => {
        const c = PALETTE[i % PALETTE.length];
        return (
          <Reveal key={i} delay={i * 55} className="flex items-start gap-2 rounded-lg p-2.5"
            style={{ background: c.bg }}>
            <span className="flex-shrink-0 h-5 w-5 rounded-full flex items-center justify-center text-[11px] font-bold"
              style={{ background: c.fg, color: "#fff" }}>{i + 1}</span>
            <span className="text-sm leading-snug" style={{ color: "var(--text)" }}>{it}</span>
          </Reveal>
        );
      })}
    </div>
  );
}

const CALLOUT = {
  tip: { fg: "#2563eb", Icon: Lightbulb, label: "Tip" },
  note: { fg: "#7c3aed", Icon: Info, label: "Note" },
  info: { fg: "#0891b2", Icon: Info, label: "Info" },
  warning: { fg: "#d97706", Icon: AlertTriangle, label: "Watch out" },
  success: { fg: "#16a34a", Icon: CheckCircle2, label: "Good to know" },
  key: { fg: "#db2777", Icon: Star, label: "Key point" },
};

export function CalloutCard({ card }) {
  const v = CALLOUT[(card.variant || "tip").toLowerCase()] || CALLOUT.tip;
  const { Icon } = v;
  return (
    <Reveal className="flex items-start gap-2.5 rounded-lg p-3 my-1 border-l-4"
      style={{ background: `${v.fg}18`, borderColor: v.fg }}>
      <Icon size={16} style={{ color: v.fg, marginTop: 1, flexShrink: 0 }} />
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: v.fg }}>{v.label}</div>
        <div className="text-sm mt-0.5" style={{ color: "var(--text)" }}>{card.text}</div>
      </div>
    </Reveal>
  );
}

export function StatsCard({ card }) {
  const tiles = card.tiles || [];
  if (!tiles.length) return null;
  return (
    <div className="flex flex-wrap gap-2 my-1">
      {tiles.map((t, i) => {
        const c = PALETTE[i % PALETTE.length];
        return (
          <Reveal key={i} delay={i * 55} className="flex-1 min-w-[110px] rounded-lg p-3 text-center"
            style={{ background: c.bg }}>
            <div className="text-lg font-bold" style={{ color: c.fg }}>{t.value}</div>
            <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>{t.label}</div>
          </Reveal>
        );
      })}
    </div>
  );
}

export function SwatchesCard({ card }) {
  const colours = card.colours || [];
  const [copied, setCopied] = useState(-1);
  if (!colours.length) return null;
  const copy = (hex, i) => {
    try { navigator.clipboard.writeText(hex); setCopied(i); setTimeout(() => setCopied(-1), 1200); } catch {}
  };
  return (
    <div className="flex flex-wrap gap-2.5 my-1">
      {colours.map((c, i) => (
        <Reveal key={i} delay={i * 50}>
          <button onClick={() => copy(c.hex, i)} className="group flex flex-col items-center w-[84px]"
            title={`Copy ${c.hex}`}>
            <span className="h-14 w-full rounded-lg border transition-transform group-hover:scale-105"
              style={{ background: c.hex, borderColor: "var(--border)" }} />
            <span className="text-[11px] font-medium mt-1 text-center leading-tight" style={{ color: "var(--text)" }}>{c.name}</span>
            <span className="text-[10px] inline-flex items-center gap-0.5" style={{ color: "var(--text-muted)" }}>
              {copied === i ? <><Check size={9} /> copied</> : <><Copy size={9} className="opacity-0 group-hover:opacity-100" /> {c.hex}</>}
            </span>
          </button>
        </Reveal>
      ))}
    </div>
  );
}
