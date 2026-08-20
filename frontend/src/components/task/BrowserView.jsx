import React, { useEffect, useRef } from "react";
import { Globe, Loader2, MousePointerClick } from "lucide-react";

// The live "browser window": the latest screenshot the agent saw + a fake address bar. When
// `interactive` is on (during a hand-off / when paused), the user can CLICK and TYPE directly on
// the view — the coordinates/keys are forwarded to the SAME server browser, so they can complete
// login / OTP / checkout themselves. The viewport matches the backend's Playwright size (1280x800),
// so the container uses that exact aspect ratio and `object-contain` — the screenshot always fits
// with NO overflow and NO stray rounded-corner clip, and click coordinates map 1:1 to the image.
const VW = 1280, VH = 800;

export default function BrowserView({ screenshot, url, title, action, interactive, onInteract }) {
  const imgRef = useRef(null);
  const stageRef = useRef(null);

  // When a hand-off starts, focus the viewport so the user can immediately type an OTP/password
  // without an extra click.
  useEffect(() => {
    if (interactive && stageRef.current) stageRef.current.focus();
  }, [interactive]);

  const send = (a, data) => { if (interactive && onInteract) onInteract({ action: a, data }); };

  const onClick = (e) => {
    if (!interactive || !imgRef.current) return;
    const r = imgRef.current.getBoundingClientRect();
    const x = Math.round(((e.clientX - r.left) / r.width) * VW);
    const y = Math.round(((e.clientY - r.top) / r.height) * VH);
    send("user_click", { x, y });
    stageRef.current?.focus();
  };

  const onKeyDown = (e) => {
    if (!interactive) return;
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      send("user_type", { text: e.key });
      e.preventDefault();
    } else if (["Enter", "Backspace", "Tab", "Delete", "Escape",
                "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
      send("user_key", { key: e.key });
      e.preventDefault();
    }
  };

  const onWheel = (e) => { if (interactive) send("user_scroll", { dy: e.deltaY }); };

  return (
    <div className="flex flex-col rounded-lg border overflow-hidden min-w-0"
      style={{ borderColor: interactive ? "var(--accent)" : "var(--border)", background: "var(--surface)" }}>
      {/* address bar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b flex-shrink-0"
        style={{ borderColor: "var(--border-subtle)", background: "var(--surface-sunken)" }}>
        <div className="flex gap-1 flex-shrink-0">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: "#ef4444" }} />
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: "#f59e0b" }} />
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: "#22c55e" }} />
        </div>
        <div className="flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded flex-1 min-w-0"
          style={{ background: "var(--surface)", color: "var(--text-muted)" }}>
          <Globe size={11} className="flex-shrink-0" /> <span className="truncate">{url || "about:blank"}</span>
        </div>
        {interactive && (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full flex-shrink-0 whitespace-nowrap"
            style={{ background: "var(--accent)", color: "#fff" }}>
            <MousePointerClick size={11} /> You're in control
          </span>
        )}
      </div>
      {/* viewport — fixed 1280:800 aspect so the screenshot never overflows or gets clipped; capped
          so it can't push the modal past the viewport height. Letterbox bg fills any spare space. */}
      <div ref={stageRef}
        className="relative w-full outline-none overflow-hidden"
        style={{ aspectRatio: `${VW} / ${VH}`, maxHeight: "68vh", background: "var(--surface-sunken)" }}
        tabIndex={interactive ? 0 : undefined} onKeyDown={onKeyDown} onWheel={onWheel}>
        {screenshot ? (
          <img ref={imgRef} src={screenshot} alt={title || "Live browser view"} onClick={onClick}
            className="absolute inset-0 w-full h-full object-contain select-none" draggable={false}
            style={{ cursor: interactive ? "crosshair" : "default" }} />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-sm"
            style={{ color: "var(--text-muted)" }}>
            <Loader2 size={16} className="animate-spin" /> Waiting for the browser…
          </div>
        )}
        {action && (
          <div className="absolute bottom-0 inset-x-0 px-3 py-2 text-xs backdrop-blur-sm"
            style={{ background: "rgba(0,0,0,0.55)", color: "#fff" }}>
            <span className="font-medium line-clamp-2">{action}</span>
          </div>
        )}
      </div>
    </div>
  );
}
