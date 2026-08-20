import React from "react";
import { Pause, Play, Square, Hand } from "lucide-react";

// Human-in-the-loop controls: pause/resume the agent, hand back after doing a sensitive step,
// or stop the run entirely. Rendered under the live browser view.
export default function TaskControls({ status, onPause, onResume, onStop, onHumanDone }) {
  const running = status === "running";
  const paused = status === "paused";
  const needsHuman = status === "needs_human";
  const finished = ["done", "failed", "stopped"].includes(status);
  if (finished) return null;

  const btn = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border";
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {needsHuman && (
        <button onClick={onHumanDone} className={btn}
          style={{ background: "var(--accent)", color: "#fff", borderColor: "var(--accent)" }}>
          <Hand size={13} /> I've done it — continue
        </button>
      )}
      {running && (
        <button onClick={onPause} className={btn} style={{ borderColor: "var(--border)", color: "var(--text)" }}>
          <Pause size={13} /> Pause
        </button>
      )}
      {paused && (
        <button onClick={onResume} className={btn} style={{ borderColor: "var(--border)", color: "var(--text)" }}>
          <Play size={13} /> Resume
        </button>
      )}
      <button onClick={onStop} className={btn}
        style={{ borderColor: "var(--destructive)", color: "var(--destructive)" }}>
        <Square size={13} /> Stop
      </button>
    </div>
  );
}
