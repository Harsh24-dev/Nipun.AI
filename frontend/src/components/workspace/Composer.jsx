import React, { useState, useRef, useEffect } from "react";
import { Send, Mic, Paperclip, Plus, Loader2, X } from "lucide-react";
import { useApp } from "@/lib/AppContext";

export default function Composer({ onSend, loading, documentScope, onClearDocScope }) {
  const { profile } = useApp();
  const [text, setText] = useState("");
  const textareaRef = useRef(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + "px";
    }
  }, [text]);

  const handleSend = () => {
    if (!text.trim() || loading) return;
    onSend(text.trim());
    setText("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t p-3" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      {documentScope && (
        <div className="flex items-center gap-2 mb-2 px-2 py-1 rounded-lg text-xs"
          style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
          <span>Answering from: {documentScope.title}</span>
          <button onClick={onClearDocScope} className="p-0.5 rounded hover:opacity-80" aria-label="Clear document scope">
            <X size={12} />
          </button>
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex-1 flex items-end rounded-xl border overflow-hidden"
          style={{ background: "var(--surface-sunken)", borderColor: "var(--border)" }}>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything…"
            rows={1}
            className="flex-1 px-4 py-3 text-sm bg-transparent outline-none resize-none"
            style={{ color: "var(--text)", maxHeight: "160px" }}
            disabled={loading}
          />
          <div className="flex items-center gap-1 pr-2 pb-2">
            {profile?.voiceEnabled && (
              <button className="p-1.5 rounded-full hover:opacity-80 transition-opacity" style={{ color: "var(--text-muted)" }} aria-label="Voice input">
                <Mic size={18} />
              </button>
            )}
            <button className="p-1.5 rounded-full hover:opacity-80 transition-opacity" style={{ color: "var(--text-muted)" }} aria-label="Attach file">
              <Paperclip size={16} />
            </button>
          </div>
        </div>
        <button onClick={handleSend} disabled={!text.trim() || loading}
          className="p-3 rounded-xl transition-all disabled:opacity-30 flex-shrink-0"
          style={{ background: "var(--accent)", color: "var(--accent-text)" }} aria-label="Send">
          {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
        </button>
      </div>

      <div className="flex items-center gap-2 mt-2 px-1">
        <span className="text-[10px] px-2 py-0.5 rounded-full border" style={{ borderColor: "var(--border-subtle)", color: "var(--text-muted)" }}>
          {profile?.ai_model === "speed" ? "Speed" : profile?.ai_model === "deep" ? "Deep" : "Auto"}
        </span>
      </div>
    </div>
  );
}