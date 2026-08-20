import React from "react";
import { Prose } from "@/components/workspace/cards/_shared";
import { DocumentCard, ComparisonTableCard, MapCard, InteractiveWidgetCard, DiagramCard, TimelineCard } from "@/components/workspace/cards/GenericCards";
import { VideoCard } from "@/components/workspace/cards/MediaCards";
import { KeyPointsCard, CalloutCard, StatsCard, SwatchesCard } from "@/components/workspace/cards/RichBlocks";

// Renders an answer as interleaved TEXT + RICH EMBEDS. The backend puts `[[embed:id]]` markers
// in the summary where a file / table / video / map / chart belongs; we render the matching
// embed there, inline, using the existing card renderers — so a deck, table, or video appears
// exactly where it's needed, not appended at the end. Any embed not referenced by a marker is
// rendered right after the prose (still inside the card).

const EMBED_MAP = {
  file: DocumentCard,
  table: ComparisonTableCard,
  comparison_table: ComparisonTableCard,
  video: VideoCard,
  map: MapCard,
  widget: InteractiveWidgetCard,
  diagram: DiagramCard,
  timeline: TimelineCard,
  keypoints: KeyPointsCard,
  callout: CalloutCard,
  stats: StatsCard,
  swatches: SwatchesCard,
};

// The lightweight rich blocks render themselves (no bordered wrapper); the heavier cards get a
// framed container. This keeps callouts/keypoints/swatches/stats feeling native to the answer.
const BARE = new Set(["keypoints", "callout", "stats", "swatches"]);

function EmbedRenderer({ embed }) {
  if (!embed) return null;
  const kind = (embed.kind || embed.cardType || "").toLowerCase();
  const Comp = EMBED_MAP[kind];
  if (!Comp) return null;
  if (BARE.has(kind)) return <div className="my-2"><Comp card={embed} /></div>;
  return (
    <div className="my-3 rounded-lg border p-3" style={{ borderColor: "var(--border-subtle)", background: "var(--surface)" }}>
      <Comp card={embed} />
    </div>
  );
}

const MARKER = /\[\[embed:([\w-]+)\]\]/g;

export default function InlineContent({ summary, embeds }) {
  const list = Array.isArray(embeds) ? embeds : [];
  const byId = Object.fromEntries(list.map((e) => [e.id, e]));
  const text = summary || "";

  // Split the summary into ordered segments: markdown text ↔ embed placeholders.
  const segments = [];
  let last = 0;
  let m;
  MARKER.lastIndex = 0;
  while ((m = MARKER.exec(text)) !== null) {
    if (m.index > last) segments.push({ text: text.slice(last, m.index) });
    segments.push({ embedId: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) segments.push({ text: text.slice(last) });

  const used = new Set(segments.filter((s) => s.embedId).map((s) => s.embedId));
  const orphans = list.filter((e) => !used.has(e.id)); // embeds with no marker → after prose

  return (
    <div>
      {segments.map((s, i) =>
        s.text !== undefined ? (
          <Prose key={i}>{s.text}</Prose>
        ) : (
          <EmbedRenderer key={i} embed={byId[s.embedId]} />
        )
      )}
      {orphans.map((e, i) => <EmbedRenderer key={`o${i}`} embed={e} />)}
    </div>
  );
}
