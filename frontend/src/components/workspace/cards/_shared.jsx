import React from "react";
import ReactMarkdown from "react-markdown";

// Shared building blocks so every card renders its TEXT content consistently and
// never drops it. Rich cards (map, diagram, video…) use these to keep the summary
// visible even when their visual payload is missing or fails to render.

export function CardTitle({ children }) {
  if (!children) return null;
  return (
    <h3 className="font-semibold text-sm mb-2" style={{ color: "var(--text)" }}>
      {children}
    </h3>
  );
}

// Renderers so INLINE media (images placed by the answer right where they belong) and links
// look right: images are constrained + rounded; links open in a new tab.
export const MD_COMPONENTS = {
  img: ({ node, ...props }) => (
    <img
      {...props}
      loading="lazy"
      alt={props.alt || ""}
      className="rounded-lg my-2 max-w-full h-auto block"
      style={{ maxHeight: 340, border: "1px solid var(--border)" }}
      onError={(e) => { e.currentTarget.style.display = "none"; }}
    />
  ),
  a: ({ node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" className="hover:underline" style={{ color: "var(--accent)" }} />
  ),
};

// Markdown body — the primary text surface for a card's `summary`. Renders inline images/charts.
export function Prose({ children, className = "" }) {
  const text = children == null ? "" : String(children);
  if (!text.trim()) return null;
  return (
    <div className={`prose prose-sm max-w-none ${className}`} style={{ color: "var(--text)" }}>
      <ReactMarkdown components={MD_COMPONENTS}>{text}</ReactMarkdown>
    </div>
  );
}

// A muted one-liner used as a caption under a visual.
export function Caption({ children }) {
  if (!children) return null;
  return (
    <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
      {children}
    </p>
  );
}

// Last-resort fallback: when a rich card has no renderable payload we still show
// its title + summary so the user is never left with an empty box.
export function TextFallback({ card, note }) {
  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      {note && <Caption>{note}</Caption>}
    </div>
  );
}
