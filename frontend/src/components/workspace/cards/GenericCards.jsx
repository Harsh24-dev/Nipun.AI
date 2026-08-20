import React, { useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";
import { FileText, ExternalLink, Download } from "lucide-react";
import { CardTitle, Prose, Caption, TextFallback } from "@/components/workspace/cards/_shared";
import { files as filesApi } from "@/lib/api";

// Leaflet's default marker images break under bundlers — wire them explicitly.
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

const isUrl = (v) => typeof v === "string" && /^https?:\/\//i.test(v);

// ── Deliverable preview (slides / pages of a generated file) ──────────────────
// Renders the SAME content as the downloadable pptx/docx: each slide/page as a framed panel
// with its heading, the plain-language explanation, bullets, chart image, and picture.
function DeliverablePreview({ preview }) {
  const slides = preview?.slides;
  if (!Array.isArray(slides) || slides.length === 0) return null;
  const isDeck = (preview.format || "").toLowerCase() === "pptx";
  const unit = isDeck ? "Slide" : "Page";

  return (
    <div className="mt-3 space-y-3">
      <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>
        Preview — {slides.length} {isDeck ? "slides" : "pages"}
      </span>
      {slides.map((s, i) => (
        <div key={i} className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--border)" }}>
          {/* slide surface */}
          <div className="p-4" style={{ background: s.is_title ? "var(--accent-subtle)" : "var(--surface)" }}>
            <div className="flex items-center justify-between gap-2">
              <h4 className={s.is_title ? "text-base font-bold" : "text-sm font-semibold"} style={{ color: "var(--text)" }}>
                {s.heading}
              </h4>
              {!s.is_title && (
                <span className="text-[10px] flex-shrink-0" style={{ color: "var(--text-muted)" }}>{unit} {i}</span>
              )}
            </div>
            {s.subtitle && <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{s.subtitle}</p>}

            {(s.bullets?.length > 0 || s.chart || s.image) && (
              <div className="mt-2 grid gap-3" style={{ gridTemplateColumns: (s.chart || s.image) ? "1fr auto" : "1fr" }}>
                <ul className="space-y-1">
                  {(s.bullets || []).map((b, j) => (
                    <li key={j} className="text-xs flex gap-1.5" style={{ color: "var(--text-secondary)" }}>
                      <span style={{ color: "var(--accent)" }}>•</span><span>{b}</span>
                    </li>
                  ))}
                </ul>
                {(s.chart || s.image) && (
                  <img src={s.chart || s.image} alt={s.heading || "visual"} className="rounded max-h-40 object-contain"
                    style={{ background: "var(--surface-sunken)" }}
                    onError={(e) => { e.currentTarget.style.display = "none"; }} />
                )}
              </div>
            )}
          </div>
          {/* the text that explains this slide/page */}
          {s.notes && (
            <div className="px-4 py-2 text-xs border-t" style={{ borderColor: "var(--border-subtle)", background: "var(--surface-sunken)", color: "var(--text-secondary)" }}>
              {s.notes}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Document ──────────────────────────────────────────────────────────────────
export function DocumentCard({ card }) {
  const dl = card.download || (card.fileUrl ? { url: card.fileUrl, filename: card.filename } : null);
  const [busy, setBusy] = React.useState(false);
  const doDownload = async () => {
    if (!dl?.url) return;
    setBusy(true);
    try { await filesApi.download(dl.url, dl.filename); } catch { /* surfaced by disabled state */ }
    setBusy(false);
  };
  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      {dl?.url && (
        <button onClick={doDownload} disabled={busy}
          className="inline-flex items-center gap-2 mt-3 px-3 py-2 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-60"
          style={{ background: "var(--accent)", color: "#fff" }}>
          <Download size={14} /> {busy ? "Preparing…" : `Download${dl.format ? " " + dl.format : ""}`}
        </button>
      )}

      {/* Inline preview — render every slide/page of the file with its explanation text */}
      <DeliverablePreview preview={card.preview} />

      {card.sources?.length > 0 && (
        <div className="space-y-1 mt-3">
          {card.sources.map((s, i) => {
            const label = typeof s === "string" ? s : s.title || s.name || s.text || "Source";
            const href = typeof s === "object" ? s.url : null;
            return (
              <div key={i} className="flex items-center gap-2 text-xs p-2 rounded" style={{ background: "var(--surface-sunken)" }}>
                <FileText size={12} style={{ color: "var(--accent)" }} />
                {isUrl(href) ? (
                  <a href={href} target="_blank" rel="noopener noreferrer" className="hover:underline" style={{ color: "var(--accent)" }}>{label}</a>
                ) : (
                  <span style={{ color: "var(--text)" }}>{label}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Timeline ────────────────────────────────────────────────────────────────
export function TimelineCard({ card }) {
  // Content can arrive as a dedicated `timeline` array OR as generic `steps`.
  const items = (card.timeline?.length ? card.timeline : card.steps) || [];
  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      {items.length > 0 && (
        <div className="space-y-3 relative pl-4 border-l-2 mt-3" style={{ borderColor: "var(--accent-subtle)" }}>
          {items.map((item, i) => (
            <div key={i} className="relative pl-4">
              <div className="absolute -left-[21px] top-1 w-3 h-3 rounded-full border-2" style={{ background: "var(--surface)", borderColor: "var(--accent)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--accent)" }}>{item.date || item.time || ""}</span>
              <p className="text-sm font-medium mt-0.5">{item.title || item.label}</p>
              {(item.description || item.desc) && <p className="text-xs" style={{ color: "var(--text-muted)" }}>{item.description || item.desc}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Comparison table ──────────────────────────────────────────────────────────
export function ComparisonTableCard({ card }) {
  // Accept BOTH the declarative `comparison_table: {columns, rows}` shape AND the
  // legacy `plan_cols`/`plan_rows` shape emitted by career/shopping agents. Either
  // way, always render the summary so the top-pick text is never dropped.
  const t = card.comparisonTable;
  let cols = t?.columns || t?.cols || card.planCols || [];
  const rows = t?.rows || card.planRows || [];
  if (cols.length === 0 && rows.length > 0) cols = Object.keys(rows[0]);

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      {rows.length > 0 && cols.length > 0 && (
        <div className="overflow-x-auto rounded-lg border mt-3" style={{ borderColor: "var(--border)" }}>
          <table className="w-full text-xs">
            <thead><tr style={{ background: "var(--surface-sunken)" }}>
              {cols.map((c, i) => <th key={i} className="px-3 py-2 text-left font-medium" style={{ color: "var(--text-secondary)" }}>{c}</th>)}
            </tr></thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  {cols.map((c, j) => {
                    const val = Array.isArray(row) ? row[j] : row[c];
                    return (
                      <td key={j} className="px-3 py-2" style={{ color: "var(--text)" }}>
                        {isUrl(val)
                          ? <a href={val} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:underline" style={{ color: "var(--accent)" }}>Open <ExternalLink size={10} /></a>
                          : (val ?? "—")}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Diagram (directed graph) ──────────────────────────────────────────────────
// Lays a small DAG out in levels (longest-path) and draws arrowed edges in SVG.
function layoutDag(nodes, edges) {
  const ids = nodes.map((n) => n.id);
  const idSet = new Set(ids);
  const adj = new Map(ids.map((id) => [id, []]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  edges.forEach((e) => {
    const from = e.from ?? e.source, to = e.to ?? e.target;
    if (idSet.has(from) && idSet.has(to)) {
      adj.get(from).push(to);
      indeg.set(to, indeg.get(to) + 1);
    }
  });
  const level = new Map(ids.map((id) => [id, 0]));
  const indegCopy = new Map(indeg);
  const queue = ids.filter((id) => indegCopy.get(id) === 0);
  let seen = 0;
  while (queue.length) {
    const id = queue.shift();
    seen++;
    adj.get(id).forEach((to) => {
      level.set(to, Math.max(level.get(to), level.get(id) + 1));
      indegCopy.set(to, indegCopy.get(to) - 1);
      if (indegCopy.get(to) === 0) queue.push(to);
    });
  }
  // Cycle fallback: if not all nodes were ordered, spread them by index.
  if (seen < ids.length) ids.forEach((id, i) => level.set(id, i));

  const byLevel = new Map();
  ids.forEach((id) => {
    const l = level.get(id);
    if (!byLevel.has(l)) byLevel.set(l, []);
    byLevel.get(l).push(id);
  });

  const NW = 130, NH = 44, GX = 28, GY = 40;
  const pos = new Map();
  let maxCols = 0;
  [...byLevel.values()].forEach((col) => { maxCols = Math.max(maxCols, col.length); });
  const width = maxCols * NW + (maxCols - 1) * GX;
  [...byLevel.entries()].sort((a, b) => a[0] - b[0]).forEach(([l, col]) => {
    const rowW = col.length * NW + (col.length - 1) * GX;
    const offset = (width - rowW) / 2;
    col.forEach((id, i) => {
      pos.set(id, { x: offset + i * (NW + GX), y: l * (NH + GY) });
    });
  });
  const levels = byLevel.size;
  return { pos, width: Math.max(width, NW), height: levels * NH + (levels - 1) * GY, NW, NH };
}

export function DiagramCard({ card }) {
  const spec = card.diagram || {};
  const nodes = Array.isArray(spec.nodes) ? spec.nodes : [];
  const edges = Array.isArray(spec.edges) ? spec.edges : [];

  const layout = useMemo(() => (nodes.length ? layoutDag(nodes, edges) : null), [card.diagram]);
  if (!layout) return <TextFallback card={card} />;

  const { pos, width, height, NW, NH } = layout;
  const labelOf = (id) => nodes.find((n) => n.id === id)?.label ?? id;

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="overflow-x-auto rounded-lg p-4 mt-3" style={{ background: "var(--surface-sunken)" }}>
        {/* viewBox makes the SVG scale to fit the card width (whole diagram visible) instead of
            being clipped; height:auto preserves the aspect ratio. */}
        <svg
          viewBox={`0 0 ${width + 4} ${height + 4}`}
          width={width + 4}
          height={height + 4}
          style={{ maxWidth: "100%", height: "auto" }}
        >
          <defs>
            <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L7,3 L0,6 Z" fill="var(--text-muted)" />
            </marker>
          </defs>
          {edges.map((e, i) => {
            const a = pos.get(e.from ?? e.source), b = pos.get(e.to ?? e.target);
            if (!a || !b) return null;
            const x1 = a.x + NW / 2, y1 = a.y + NH, x2 = b.x + NW / 2, y2 = b.y;
            return (
              <g key={i}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--text-muted)" strokeWidth="1.5" markerEnd="url(#arrow)" />
                {(e.label) && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2} fontSize="9" fill="var(--text-muted)" textAnchor="middle">{e.label}</text>}
              </g>
            );
          })}
          {nodes.map((n) => {
            const p = pos.get(n.id);
            if (!p) return null;
            return (
              <g key={n.id}>
                <rect x={p.x} y={p.y} width={NW} height={NH} rx="8" fill="var(--surface)" stroke="var(--accent)" strokeWidth="1.5" />
                <foreignObject x={p.x} y={p.y} width={NW} height={NH}>
                  <div style={{ width: NW, height: NH, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "2px 6px", fontSize: 11, lineHeight: 1.15, color: "var(--text)" }}>
                    {labelOf(n.id)}
                  </div>
                </foreignObject>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ── Mind map (radial) ─────────────────────────────────────────────────────────
export function MindmapCard({ card }) {
  const nodes = card.mindmapNodes || [];

  const layout = useMemo(() => {
    if (nodes.length === 0) return null;
    const W = 460, H = Math.max(220, 90 + nodes.length * 12);
    const cx = W / 2, cy = H / 2;
    const hasCoords = nodes.every((n) => typeof n.x === "number" && typeof n.y === "number");
    const positions = new Map();
    if (hasCoords) {
      const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      const sx = maxX > minX ? (W - 120) / (maxX - minX) : 0;
      const sy = maxY > minY ? (H - 60) / (maxY - minY) : 0;
      nodes.forEach((n) => positions.set(n.id, { x: 60 + (n.x - minX) * sx, y: 30 + (n.y - minY) * sy }));
    } else {
      // First node in the center, the rest around a ring.
      positions.set(nodes[0].id, { x: cx, y: cy });
      const rest = nodes.slice(1);
      const r = Math.min(cx, cy) - 40;
      rest.forEach((n, i) => {
        const a = (i / rest.length) * Math.PI * 2 - Math.PI / 2;
        positions.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
      });
    }
    return { positions, W, H };
  }, [card.mindmapNodes]);

  if (!layout) return <TextFallback card={card} />;
  const { positions, W, H } = layout;

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <div className="overflow-x-auto rounded-lg p-2 mt-1" style={{ background: "var(--surface-sunken)" }}>
        <svg width={W} height={H} style={{ maxWidth: "100%" }}>
          {nodes.map((n) =>
            (n.connections || []).map((cid, j) => {
              const a = positions.get(n.id), b = positions.get(cid);
              if (!a || !b) return null;
              return <line key={`${n.id}-${cid}-${j}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--border)" strokeWidth="1.5" />;
            })
          )}
          {nodes.map((n, i) => {
            const p = positions.get(n.id);
            const w = Math.min(150, 30 + (n.label?.length || 4) * 7);
            return (
              <foreignObject key={n.id} x={p.x - w / 2} y={p.y - 15} width={w} height={30}>
                <div style={{ width: w, height: 30, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", fontSize: 11, padding: "0 6px", borderRadius: 8, background: i === 0 ? "var(--accent-subtle)" : "var(--surface)", border: `1px solid ${i === 0 ? "var(--accent)" : "var(--border)"}`, color: "var(--text)" }}>
                  {n.label}
                </div>
              </foreignObject>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ── Map (real Leaflet) ────────────────────────────────────────────────────────
export function MapCard({ card }) {
  const data = card.mapData || {};
  const markers = (Array.isArray(data.markers) ? data.markers : [])
    .map((m) => ({
      lat: Number(m.lat ?? m.latitude ?? (Array.isArray(m.position) ? m.position[0] : undefined)),
      lng: Number(m.lng ?? m.lon ?? m.longitude ?? (Array.isArray(m.position) ? m.position[1] : undefined)),
      label: m.label || m.name || m.title || "",
      description: m.description || m.desc || "",
    }))
    .filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lng));

  // Need at least a center or one marker to draw a real map; else keep the text.
  const center = Array.isArray(data.center) && data.center.length === 2
    ? [Number(data.center[0]), Number(data.center[1])]
    : markers.length
      ? [markers.reduce((s, m) => s + m.lat, 0) / markers.length, markers.reduce((s, m) => s + m.lng, 0) / markers.length]
      : null;

  if (!center) return <TextFallback card={card} note="No location coordinates were provided for this map." />;

  const zoom = Number(data.zoom) || (markers.length > 1 ? 11 : 13);

  return (
    <div>
      <CardTitle>{card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="rounded-lg overflow-hidden mt-3 border" style={{ borderColor: "var(--border)" }}>
        <MapContainer center={center} zoom={zoom} style={{ height: 260, width: "100%" }} scrollWheelZoom={false}>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {markers.map((m, i) => (
            <Marker key={i} position={[m.lat, m.lng]}>
              {(m.label || m.description) && (
                <Popup>
                  {m.label && <strong>{m.label}</strong>}
                  {m.description && <div>{m.description}</div>}
                </Popup>
              )}
            </Marker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}

// ── Interactive widget (calculators) ──────────────────────────────────────────
const WIDGET_KINDS = {
  emi: (v) => {
    const P = v.principal ?? v.amount ?? v.loan ?? 0;
    const r = (v.rate ?? v.interest ?? 0) / 1200;
    const n = v.tenure ?? v.months ?? v.term ?? 0;
    if (!P || !n) return null;
    const emi = r === 0 ? P / n : (P * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
    return { label: "Monthly EMI", value: emi, extra: [["Total payable", emi * n], ["Total interest", emi * n - P]] };
  },
  sip: (v) => {
    const M = v.monthly ?? v.amount ?? v.investment ?? 0;
    const i = (v.rate ?? v.return ?? 0) / 1200;
    const n = v.months ?? v.tenure ?? (v.years ? v.years * 12 : 0);
    if (!M || !n) return null;
    const fv = i === 0 ? M * n : M * ((Math.pow(1 + i, n) - 1) / i) * (1 + i);
    return { label: "Maturity value", value: fv, extra: [["Invested", M * n], ["Gain", fv - M * n]] };
  },
  simple_interest: (v) => {
    const P = v.principal ?? v.amount ?? 0;
    const r = v.rate ?? 0;
    const t = v.years ?? v.time ?? v.tenure ?? 0;
    if (!P) return null;
    const si = (P * r * t) / 100;
    return { label: "Interest", value: si, extra: [["Total amount", P + si]] };
  },
};

function defaultInputs(kind) {
  switch (kind) {
    case "emi": return [
      { name: "principal", label: "Loan amount (₹)", default: 500000 },
      { name: "rate", label: "Interest rate (% p.a.)", default: 9, step: 0.1 },
      { name: "tenure", label: "Tenure (months)", default: 60 },
    ];
    case "sip": return [
      { name: "monthly", label: "Monthly investment (₹)", default: 5000 },
      { name: "rate", label: "Expected return (% p.a.)", default: 12, step: 0.1 },
      { name: "months", label: "Duration (months)", default: 120 },
    ];
    case "simple_interest": return [
      { name: "principal", label: "Principal (₹)", default: 100000 },
      { name: "rate", label: "Rate (% p.a.)", default: 8, step: 0.1 },
      { name: "years", label: "Time (years)", default: 5 },
    ];
    default: return [];
  }
}

const fmt = (n) => (Number.isFinite(n) ? "₹" + Math.round(n).toLocaleString("en-IN") : "—");

export function InteractiveWidgetCard({ card }) {
  const spec = card.widget || {};
  const kind = spec.kind || spec.type;
  const compute = WIDGET_KINDS[kind];
  const inputs = (Array.isArray(spec.inputs) && spec.inputs.length ? spec.inputs : defaultInputs(kind));

  const [values, setValues] = useState(() =>
    Object.fromEntries(inputs.map((f) => [f.name, Number(f.default ?? 0)]))
  );

  // No known calculator AND no declared inputs → just show the text content.
  if (!compute && inputs.length === 0) return <TextFallback card={card} />;

  const result = compute ? compute(values) : null;

  return (
    <div>
      <CardTitle>{spec.title || card.title}</CardTitle>
      <Prose>{card.summary}</Prose>
      <div className="p-4 rounded-lg mt-3 space-y-3" style={{ background: "var(--surface-sunken)" }}>
        {inputs.map((f) => (
          <div key={f.name}>
            <label className="flex items-center justify-between text-xs mb-1" style={{ color: "var(--text-secondary)" }}>
              <span>{f.label || f.name}</span>
              <span className="font-mono" style={{ color: "var(--text)" }}>{values[f.name]}</span>
            </label>
            <input
              type="number"
              step={f.step || 1}
              value={values[f.name]}
              onChange={(e) => setValues((p) => ({ ...p, [f.name]: Number(e.target.value) }))}
              className="w-full px-3 py-2 rounded-lg text-sm border outline-none"
              style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
            />
          </div>
        ))}
        {result && (
          <div className="pt-3 border-t" style={{ borderColor: "var(--border-subtle)" }}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>{result.label}</span>
              <span className="text-lg font-bold" style={{ color: "var(--accent)" }}>{fmt(result.value)}</span>
            </div>
            {result.extra?.map(([k, val]) => (
              <div key={k} className="flex items-center justify-between text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                <span>{k}</span><span>{fmt(val)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
