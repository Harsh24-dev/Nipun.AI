import React, { useEffect, useState } from "react";
import {
  ThumbsUp, ThumbsDown, Volume2, VolumeX, Copy, Check, Maximize2,
  MessageSquare, CloudSun, Scale, Sprout, FileText, Code, HelpCircle,
  GitBranch, MapPin, Clock, ArrowRightLeft, Layout, AlertTriangle, Zap,
  Play, Globe, PenTool, BookOpen
} from "lucide-react";
import { useApp } from "@/lib/AppContext";
import { feedback as feedbackApi, explain as explainApi } from "@/lib/api";
import { LANGUAGES } from "@/lib/i18n";

// Human-readable labels for the "rephrase" chips (so "in_en" reads "In English", not "in en").
function explainLabel(mode) {
  if (mode?.startsWith("in_")) {
    const code = mode.slice(3);
    const lang = LANGUAGES.find((l) => l.code === code);
    return "In " + (lang ? lang.label : code.toUpperCase());
  }
  const map = { simpler: "Simpler", deeper: "More detail", with_example: "With example" };
  return map[mode] || mode.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

import AnswerCard from "@/components/workspace/cards/AnswerCard";
import AgentTaskCard from "@/components/workspace/cards/AgentTaskCard";
import StepActionCard from "@/components/workspace/cards/StepActionCard";
import PlanCard from "@/components/workspace/cards/PlanCard";
import PriceTableCard from "@/components/workspace/cards/PriceTableCard";
import WeatherCard from "@/components/workspace/cards/WeatherCard";
import SchemeListCard from "@/components/workspace/cards/SchemaListCard";
import ClarifyCard from "@/components/workspace/cards/ClarifyCard";
import CodeEditorCard from "@/components/workspace/cards/CodeEditorCard";
import ErrorCard from "@/components/workspace/cards/ErrorCard";
import { DocumentCard, MindmapCard, TimelineCard, ComparisonTableCard, DiagramCard, MapCard, InteractiveWidgetCard } from "@/components/workspace/cards/GenericCards";
import { VideoCard, BrowserCard, WhiteboardCard, BookCard } from "@/components/workspace/cards/MediaCards";
import { TextFallback } from "@/components/workspace/cards/_shared";
import CardErrorBoundary from "@/components/workspace/cards/CardErrorBoundary";
import ResourcesSection from "@/components/workspace/ResourcesSection";

const CARD_MAP = {
  answer: { component: AnswerCard, icon: MessageSquare, label: "Answer", color: "var(--accent)" },
  agent_task: { component: AgentTaskCard, icon: Zap, label: "Task", color: "var(--accent)" },
  step_action: { component: StepActionCard, icon: Zap, label: "Steps", color: "var(--success)" },
  plan: { component: PlanCard, icon: Layout, label: "Plan", color: "var(--accent)" },
  price_table: { component: PriceTableCard, icon: Sprout, label: "Prices", color: "var(--success)" },
  weather: { component: WeatherCard, icon: CloudSun, label: "Weather", color: "#3B82F6" },
  scheme_list: { component: SchemeListCard, icon: Scale, label: "Schemes", color: "var(--accent)" },
  clarify: { component: ClarifyCard, icon: HelpCircle, label: "Clarification", color: "var(--warning)" },
  code_editor: { component: CodeEditorCard, icon: Code, label: "Code", color: "#8B5CF6" },
  document: { component: DocumentCard, icon: FileText, label: "Document", color: "var(--accent)" },
  mindmap: { component: MindmapCard, icon: GitBranch, label: "Mind Map", color: "#10B981" },
  timeline: { component: TimelineCard, icon: Clock, label: "Timeline", color: "var(--accent)" },
  comparison_table: { component: ComparisonTableCard, icon: ArrowRightLeft, label: "Comparison", color: "#6366F1" },
  diagram: { component: DiagramCard, icon: GitBranch, label: "Diagram", color: "#8B5CF6" },
  illustrative_diagram: { component: DiagramCard, icon: GitBranch, label: "Diagram", color: "#8B5CF6" },
  map: { component: MapCard, icon: MapPin, label: "Map", color: "#10B981" },
  interactive_widget: { component: InteractiveWidgetCard, icon: Layout, label: "Widget", color: "var(--accent)" },
  video: { component: VideoCard, icon: Play, label: "Video", color: "#EF4444" },
  browser: { component: BrowserCard, icon: Globe, label: "Web", color: "#3B82F6" },
  whiteboard: { component: WhiteboardCard, icon: PenTool, label: "Whiteboard", color: "#F59E0B" },
  book: { component: BookCard, icon: BookOpen, label: "Book", color: "var(--accent)" },
  error: { component: ErrorCard, icon: AlertTriangle, label: "Error", color: "var(--destructive)" },
};

function resolveCard(cardType) {
  // Normalize to the snake_case keys used in CARD_MAP. Also de-camelCase so a backend
  // type like "priceTable" resolves to "price_table" instead of silently falling back
  // to AnswerCard. snake_case and hyphenated/spaced types keep working.
  const normalized = cardType == null ? "" : String(cardType)
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[\s-]+/g, "_")
    .toLowerCase();
  const hit = CARD_MAP[normalized];
  // `fallback` flags an UNKNOWN backend card type so the renderer can show a safe text fallback
  // (never a blank box) when a brand-new type also carries no summary/title to render as an answer.
  return hit ? { ...hit, fallback: false } : { ...CARD_MAP.answer, fallback: true };
}

// DELIVER-WITH-SCORE — how each reliability band is presented in the UI. We always
// SHOW the answer; low/very_low bands get a visible warning ("unsure of this answer")
// rather than the answer being hidden.
const RELIABILITY_STYLE = {
  high:     { fg: "var(--success)",     bg: "var(--surface-sunken)", label: "Reliable" },
  medium:   { fg: "var(--text-muted)",  bg: "var(--surface-sunken)", label: "Fairly reliable" },
  low:      { fg: "var(--warning)",     bg: "var(--surface-sunken)", label: "Low confidence" },
  very_low: { fg: "var(--destructive)", bg: "var(--surface-sunken)", label: "Unverified" },
};

// Normalize whatever the backend sent into a single view model. Supports both the rich
// `reliability` object and the flat `confidence`/`low_confidence` fields.
function bandFromScore(score) {
  if (score >= 0.75) return "high";
  if (score >= 0.5) return "medium";
  if (score >= 0.3) return "low";
  return "very_low";
}

function reliabilityView(card) {
  const rel = card.reliability;
  if (rel && rel.applicable === false) return null;            // conversational — no badge
  const score = rel?.score ?? card.confidence ?? null;
  if (score == null && !rel?.band) return null;
  // Prefer the backend band; otherwise derive it from the score so a flat-confidence
  // card (e.g. plan preview) still gets a consistent label instead of a default.
  const band = rel?.band || (score != null ? bandFromScore(score) : "medium");
  const style = RELIABILITY_STYLE[band] || RELIABILITY_STYLE.medium;
  const warn = rel?.warn ?? card.lowConfidence ?? (score != null && score < 0.5);
  return {
    pct: score != null ? Math.round(score * 100) : null,
    label: rel?.label || style.label,
    reasons: rel?.reasons || [],
    unsupported: rel?.unsupported_claims || [],
    warn,
    style,
  };
}

export default function ResponseCardRenderer({ card, onSubmitClarification, onSendQuery }) {
  const { profile } = useApp();
  const [feedbackGiven, setFeedbackGiven] = useState(null);
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [showReliability, setShowReliability] = useState(false);

  const entry = resolveCard(card.cardType);
  const CardComponent = entry.component;
  const Icon = entry.icon;
  const rel = reliabilityView(card);

  const handleFeedback = async (rating) => {
    setFeedbackGiven(rating);
    try {
      await feedbackApi.send({ correlation_id: card.correlationId, rating });
    } catch {}
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(card.summary || card.speechText || "");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleReadAloud = () => {
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const text = card.speechText || card.summary || "";
    if (!text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = card.language || "en";
    utterance.onend = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
    setSpeaking(true);
  };

  const handleExplain = async (mode) => {
    try {
      await explainApi.differently({ mode, correlation_id: card.correlationId });
    } catch {}
    if (onSendQuery) {
      const prompts = {
        simpler: "explain that more simply",
        deeper: "explain in more detail",
        with_example: "explain with an example",
      };
      onSendQuery(prompts[mode] || `explain differently: ${mode}`);
    }
  };

  return (
    <div className="group relative">
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={12} style={{ color: entry.color }} />
        <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: entry.color }}>
          {entry.label}
        </span>
        {card.language && card.language !== "en" && (
          <span className="text-[10px] px-1.5 py-0.5 rounded ml-1" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
            {card.language}
          </span>
        )}
      </div>

      <CardErrorBoundary card={card}>
        {entry.fallback && !card.summary && !card.title ? (
          <TextFallback card={card} note={`Unsupported card type "${card.cardType}".`} />
        ) : (
          <CardComponent card={card} onSubmitClarification={onSubmitClarification} />
        )}
      </CardErrorBoundary>

      {/* Study resources — videos / images / links to see & explore the topic */}
      <ResourcesSection resources={card.resources} />

      {card.sources?.length > 0 && card.cardType !== "document" && (
        <div className="mt-3 pt-2 border-t" style={{ borderColor: "var(--border-subtle)" }}>
          <span className="text-[10px] font-medium" style={{ color: "var(--text-muted)" }}>Sources</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {card.sources.map((s, i) => {
              const label = typeof s === "string" ? s : s.title || s.name || s.text || `[${i + 1}]`;
              const url = typeof s === "object" ? s.url : null;
              const cls = "text-[10px] px-1.5 py-0.5 rounded";
              const style = { background: "var(--surface-sunken)", color: url ? "var(--accent)" : "var(--text-muted)" };
              return url && /^https?:\/\//i.test(url) ? (
                <a key={i} href={url} target="_blank" rel="noopener noreferrer" className={`${cls} hover:underline`} style={style} title={url}>
                  {label}
                </a>
              ) : (
                <span key={i} className={cls} style={style}>{label}</span>
              );
            })}
          </div>
        </div>
      )}

      {card.disclaimer && (
        <p className="text-[10px] mt-2 italic" style={{ color: "var(--text-muted)" }}>
          ⚠ {card.disclaimer}
        </p>
      )}

      {/* Footer: quick actions (on hover) on the left, reliability circle always at the corner */}
      <div className="flex items-center justify-between gap-2 mt-3 pt-2 border-t"
        style={{ borderColor: "var(--border-subtle)" }}>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {profile?.voiceEnabled && card.speechText && (
            <button onClick={handleReadAloud} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] hover:opacity-80"
              style={{ color: "var(--text-muted)" }} aria-label={speaking ? "Stop reading" : "Read aloud"}>
              {speaking ? <VolumeX size={12} /> : <Volume2 size={12} />}
              {speaking ? "Stop" : "Read"}
            </button>
          )}
          <button onClick={() => handleFeedback(1)} className="p-1 rounded hover:opacity-80" aria-label="Helpful" aria-pressed={feedbackGiven === 1}
            style={{ color: feedbackGiven === 1 ? "var(--success)" : "var(--text-muted)" }}>
            <ThumbsUp size={12} />
          </button>
          <button onClick={() => handleFeedback(-1)} className="p-1 rounded hover:opacity-80" aria-label="Not helpful" aria-pressed={feedbackGiven === -1}
            style={{ color: feedbackGiven === -1 ? "var(--destructive)" : "var(--text-muted)" }}>
            <ThumbsDown size={12} />
          </button>
          <button onClick={handleCopy} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] hover:opacity-80"
            style={{ color: "var(--text-muted)" }} aria-label="Copy">
            {copied ? <Check size={10} /> : <Copy size={10} />}
          </button>
        </div>

        {/* Reliability — a small circle in the corner. CLICK it to see what the number means:
            a plain-language explanation + why. Only shown when a score applies (not for
            conversational replies). */}
        {rel && rel.pct != null && (
          <div className="relative flex-shrink-0">
            <button
              onClick={() => setShowReliability((v) => !v)}
              className="h-7 w-7 rounded-full flex items-center justify-center text-[10px] font-bold hover:opacity-80"
              style={{ color: rel.style.fg, border: `2px solid ${rel.style.fg}`, background: "var(--surface)" }}
              aria-label={`Reliability ${rel.pct} percent, ${rel.label}. Tap for details.`}
              aria-expanded={showReliability}
            >
              {rel.pct}
            </button>
            {showReliability && (
              <>
                {/* click-away backdrop */}
                <div className="fixed inset-0 z-10" onClick={() => setShowReliability(false)} />
                <div className="absolute bottom-9 right-0 z-20 w-64 p-3 rounded-lg border shadow-lg text-xs"
                  style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold" style={{ color: rel.style.fg }}>{rel.pct}% · {rel.label}</span>
                    <button onClick={() => setShowReliability(false)} aria-label="Close" style={{ color: "var(--text-muted)" }}>×</button>
                  </div>
                  <p style={{ color: "var(--text-secondary)" }}>
                    This is a <strong>reliability score</strong> — our estimate of how well this answer is
                    backed by trustworthy sources. Higher means better grounded; lower means please
                    double-check important details.
                  </p>
                  {rel.reasons.length > 0 && (
                    <ul className="mt-2 list-disc pl-4 space-y-0.5" style={{ color: "var(--text-muted)" }}>
                      {rel.reasons.map((r, i) => <li key={i}>{r}</li>)}
                    </ul>
                  )}
                  <div className="mt-2 pt-2 border-t flex flex-wrap gap-x-3 gap-y-1 text-[10px]" style={{ borderColor: "var(--border-subtle)", color: "var(--text-muted)" }}>
                    <span><span style={{ color: "var(--success)" }}>●</span> 75%+ reliable</span>
                    <span><span style={{ color: "var(--warning)" }}>●</span> 50–74% fair</span>
                    <span><span style={{ color: "var(--destructive)" }}>●</span> &lt;50% verify</span>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Rephrase controls — clearly labelled so they don't read as stray words. On hover. */}
      {(card.explainDifferently || []).length > 0 && (
        <div className="flex items-center gap-1.5 mt-2 flex-wrap opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>Rephrase:</span>
          {card.explainDifferently.map(mode => (
            <button key={mode} onClick={() => handleExplain(mode)}
              className="px-2.5 py-0.5 rounded-full text-[10px] border hover:opacity-80"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
              {explainLabel(mode)}
            </button>
          ))}
        </div>
      )}

      {/* Suggested follow-up questions from the backend — tap to ask. Only shown when a
          send handler is wired, so it can never render a dead chip. */}
      {onSendQuery && (card.followups || []).length > 0 && (
        <div className="flex items-center gap-1.5 mt-2 flex-wrap">
          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>Ask next:</span>
          {card.followups.filter(Boolean).map((q, i) => (
            <button key={i} onClick={() => onSendQuery(typeof q === "string" ? q : (q.text || q.label || ""))}
              className="px-2.5 py-0.5 rounded-full text-[11px] border hover:opacity-80"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
              {typeof q === "string" ? q : (q.text || q.label || "")}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}