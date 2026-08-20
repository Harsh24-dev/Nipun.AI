import React, { useEffect, useState } from "react";
import { Brain, Search, Layers, Sparkles, PenTool, Palette } from "lucide-react";
import { Reveal } from "@/components/workspace/cards/RichBlocks";

// A dynamic, story-like "thinking" indicator. The backend sends one `thinking` signal, so the UI
// narrates the likely journey — understanding → searching → reasoning → composing → visualising —
// with a colour-shifting animated icon, a live progress bar and animated dots. This keeps the user
// engaged and watching while the grounded answer is being generated, instead of a static spinner.

const STAGES = [
  { Icon: Brain, text: "Understanding your question", color: "#7c3aed" },
  { Icon: Search, text: "Searching trusted sources", color: "#2563eb" },
  { Icon: Layers, text: "Gathering the best information", color: "#0891b2" },
  { Icon: Sparkles, text: "Reasoning it through", color: "#db2777" },
  { Icon: PenTool, text: "Composing your answer", color: "#d97706" },
  { Icon: Palette, text: "Adding visuals & structure", color: "#16a34a" },
];

function Dots() {
  const [n, setN] = useState(1);
  useEffect(() => {
    const t = setInterval(() => setN((p) => (p % 3) + 1), 400);
    return () => clearInterval(t);
  }, []);
  return <span style={{ letterSpacing: 1 }}>{".".repeat(n)}</span>;
}

export default function ThinkingIndicator() {
  const [i, setI] = useState(0);
  useEffect(() => {
    // Advance through the stages; hold on the last one if generation runs long, then loop the
    // final "composing/visualising" beats so it always feels alive.
    const t = setInterval(() => setI((p) => (p + 1 < STAGES.length ? p + 1 : STAGES.length - 2)), 1900);
    return () => clearInterval(t);
  }, []);
  const s = STAGES[i] || STAGES[0];
  const { Icon } = s;
  const pct = Math.round(((i + 1) / STAGES.length) * 100);

  return (
    <div className="flex justify-start">
      <div className="px-3.5 py-3 rounded-2xl rounded-bl-sm border inline-flex items-center gap-3"
        style={{ background: "var(--surface)", borderColor: "var(--border)", minWidth: 240 }}>
        {/* colour-shifting animated icon with a soft ping halo */}
        <span className="relative h-9 w-9 rounded-full flex items-center justify-center flex-shrink-0"
          style={{ background: `${s.color}1e`, transition: "background .5s ease" }}>
          <span className="absolute inset-0 rounded-full animate-ping" style={{ background: `${s.color}20` }} />
          <Reveal key={i}><Icon size={17} style={{ color: s.color, transition: "color .5s ease" }} /></Reveal>
        </span>
        <div className="min-w-0">
          <Reveal key={i} className="text-sm font-medium flex items-center" style={{ color: "var(--text)" }}>
            {s.text}<Dots />
          </Reveal>
          <div className="mt-1.5 h-1 w-44 rounded-full overflow-hidden" style={{ background: "var(--surface-sunken)" }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: s.color, transition: "width .6s ease, background .5s ease" }} />
          </div>
        </div>
      </div>
    </div>
  );
}
