import React from "react";
import { Play, ExternalLink, Globe, BookOpen, StickyNote } from "lucide-react";
import { CardTitle, Prose, Caption, TextFallback } from "@/components/workspace/cards/_shared";

const firstUrl = (card) =>
  card.url || card._raw?.video_url || card._raw?.embed_url || card._raw?.link || null;

// ── Video (YouTube / Vimeo / generic embed) ───────────────────────────────────
function youtubeId(url = "") {
  const m = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)([\w-]{11})/);
  return m ? m[1] : null;
}
function vimeoId(url = "") {
  const m = url.match(/vimeo\.com\/(?:video\/)?(\d+)/);
  return m ? m[1] : null;
}

export function VideoCard({ card }) {
  const url = firstUrl(card);
  const yt = youtubeId(url) || card._raw?.video_id;
  const vm = vimeoId(url);
  const embed = yt ? `https://www.youtube.com/embed/${yt}` : vm ? `https://player.vimeo.com/video/${vm}` : null;

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      {embed ? (
        <div className="rounded-lg overflow-hidden mt-3 border" style={{ borderColor: "var(--border)", aspectRatio: "16 / 9" }}>
          <iframe
            src={embed}
            title={card.title || "Video"}
            className="w-full h-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            frameBorder="0"
          />
        </div>
      ) : url ? (
        <a href={url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-2 mt-3 px-3 py-2 rounded-lg text-sm hover:opacity-80"
          style={{ background: "var(--surface-sunken)", color: "var(--accent)" }}>
          <Play size={14} /> Watch video <ExternalLink size={12} />
        </a>
      ) : (
        <Caption>No video link was provided.</Caption>
      )}
    </div>
  );
}

// ── Browser / web embed ───────────────────────────────────────────────────────
// Many sites forbid iframing (X-Frame-Options / CSP), so we always offer a real
// link alongside the embed attempt.
export function BrowserCard({ card }) {
  const url = firstUrl(card);
  if (!url) return <TextFallback card={card} note="No web page link was provided." />;

  let host = url;
  try { host = new URL(url).host; } catch { /* keep raw */ }

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="mt-3 rounded-lg border overflow-hidden" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs" style={{ background: "var(--surface-sunken)", color: "var(--text-muted)" }}>
          <span className="flex items-center gap-1.5 truncate"><Globe size={12} /> {host}</span>
          <a href={url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 hover:underline flex-shrink-0" style={{ color: "var(--accent)" }}>
            Open <ExternalLink size={10} />
          </a>
        </div>
        <iframe
          src={url}
          title={card.title || host}
          className="w-full"
          style={{ height: 320, background: "var(--surface)" }}
          sandbox="allow-scripts allow-same-origin allow-popups"
          referrerPolicy="no-referrer"
        />
      </div>
      <Caption>If the page doesn't load here, some sites block embedding — use “Open”.</Caption>
    </div>
  );
}

// ── Whiteboard (notes board) ──────────────────────────────────────────────────
// Renders the answer as a board of sticky notes drawn from steps / options /
// mindmap nodes, keeping the summary as the board's heading text.
export function WhiteboardCard({ card }) {
  const notes = [
    ...(card.steps || []).map((s) => ({ title: s.title, body: s.desc || s.description })),
    ...(card.mindmapNodes || []).map((n) => ({ title: n.label, body: "" })),
    ...(card.options || []).map((o) => ({ title: typeof o === "string" ? o : o.label, body: "" })),
  ].filter((n) => n.title);

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      {notes.length > 0 && (
        <div
          className="mt-3 p-4 rounded-lg grid grid-cols-2 sm:grid-cols-3 gap-2"
          style={{ background: "repeating-linear-gradient(45deg, var(--surface-sunken), var(--surface-sunken) 12px, var(--surface) 12px, var(--surface) 24px)" }}
        >
          {notes.map((n, i) => (
            <div key={i} className="p-2 rounded shadow-sm text-xs" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
              <div className="flex items-start gap-1">
                <StickyNote size={11} className="mt-0.5 flex-shrink-0" style={{ color: "var(--accent)" }} />
                <div>
                  <p className="font-medium" style={{ color: "var(--text)" }}>{n.title}</p>
                  {n.body && <p className="mt-0.5" style={{ color: "var(--text-muted)" }}>{n.body}</p>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Book / long-form reader ───────────────────────────────────────────────────
// Chapters may arrive as card.book.chapters, card._raw.chapters, or as sources.
export function BookCard({ card }) {
  const book = card.book || card._raw?.book || {};
  const author = book.author || card._raw?.author;
  const chapters =
    (Array.isArray(book.chapters) && book.chapters) ||
    (Array.isArray(card._raw?.chapters) && card._raw.chapters) ||
    [];

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <BookOpen size={16} style={{ color: "var(--accent)" }} />
        <div>
          <h3 className="font-semibold text-sm" style={{ color: "var(--text)" }}>{book.title || card.title}</h3>
          {author && <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>by {author}</p>}
        </div>
      </div>
      <div className="rounded-lg p-4 max-h-[420px] overflow-y-auto" style={{ background: "var(--surface-sunken)" }}>
        <Prose>{book.content || card.summary}</Prose>
        {chapters.length > 0 && (
          <div className="mt-3 space-y-3">
            {chapters.map((ch, i) => (
              <div key={i}>
                <h4 className="text-xs font-semibold mb-1" style={{ color: "var(--accent)" }}>
                  {ch.title || `Chapter ${i + 1}`}
                </h4>
                <Prose>{ch.content || ch.text || ch.summary}</Prose>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
