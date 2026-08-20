import React from "react";
import { Play, ExternalLink, ImageIcon, FileText } from "lucide-react";

// "Learn & explore" — the visual/media companion to a text answer. Renders study VIDEOS,
// IMAGES/diagrams, and reference ARTICLE links the backend gathered for a learning question.
// Fully defensive: any missing group is skipped; a broken image/thumbnail just hides itself.

function youtubeId(url = "") {
  const m = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([\w-]{11})/);
  return m ? m[1] : null;
}

function ytThumb(url) {
  const id = youtubeId(url);
  return id ? `https://img.youtube.com/vi/${id}/mqdefault.jpg` : null;
}

function SectionLabel({ icon: Icon, children }) {
  return (
    <div className="flex items-center gap-1.5 mb-1.5">
      <Icon size={12} style={{ color: "var(--accent)" }} />
      <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {children}
      </span>
    </div>
  );
}

export default function ResourcesSection({ resources }) {
  if (!resources) return null;
  const videos = Array.isArray(resources.videos) ? resources.videos : [];
  const images = Array.isArray(resources.images) ? resources.images : [];
  const articles = Array.isArray(resources.articles) ? resources.articles : [];
  if (!videos.length && !images.length && !articles.length) return null;

  return (
    <div className="mt-3 pt-3 border-t space-y-3" style={{ borderColor: "var(--border-subtle)" }}>
      <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>
        Learn &amp; explore
      </span>

      {/* Videos — thumbnail + title, opens the video in a new tab */}
      {videos.length > 0 && (
        <div>
          <SectionLabel icon={Play}>Videos</SectionLabel>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {videos.map((v, i) => {
              const thumb = ytThumb(v.url);
              return (
                <a key={i} href={v.url} target="_blank" rel="noopener noreferrer"
                  className="group/vid block rounded-lg overflow-hidden border hover:opacity-90"
                  style={{ borderColor: "var(--border)" }} title={v.title}>
                  <div className="relative" style={{ aspectRatio: "16 / 9", background: "var(--surface-sunken)" }}>
                    {thumb && (
                      <img src={thumb} alt={v.title || "video"} className="w-full h-full object-cover"
                        onError={(e) => { e.currentTarget.style.display = "none"; }} />
                    )}
                    <span className="absolute inset-0 flex items-center justify-center">
                      <span className="rounded-full p-1.5" style={{ background: "rgba(0,0,0,0.55)" }}>
                        <Play size={14} color="#fff" fill="#fff" />
                      </span>
                    </span>
                  </div>
                  <p className="text-[10px] p-1.5 line-clamp-2" style={{ color: "var(--text)" }}>{v.title}</p>
                </a>
              );
            })}
          </div>
        </div>
      )}

      {images.length > 0 && (
        <div>
          <SectionLabel icon={ImageIcon}>Pictures &amp; diagrams</SectionLabel>
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            {images.map((img, i) => (
              <a key={i} href={img.link || img.url} target="_blank" rel="noopener noreferrer"
                className="block rounded-lg overflow-hidden border hover:opacity-90"
                style={{ borderColor: "var(--border)" }} title={img.title}>
                <img src={img.thumbnail || img.url} alt={img.title || "illustration"}
                  className="w-full object-cover" style={{ aspectRatio: "1 / 1", background: "var(--surface-sunken)" }}
                  loading="lazy" onError={(e) => { e.currentTarget.closest("a").style.display = "none"; }} />
              </a>
            ))}
          </div>
        </div>
      )}

      {articles.length > 0 && (
        <div>
          <SectionLabel icon={FileText}>Read more</SectionLabel>
          <div className="flex flex-col gap-1">
            {articles.map((a, i) => (
              <a key={i} href={a.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs hover:underline"
                style={{ color: "var(--accent)" }} title={a.url}>
                <ExternalLink size={11} className="flex-shrink-0" />
                <span className="truncate">{a.title || a.source || a.url}</span>
                {a.source && <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>· {a.source}</span>}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
