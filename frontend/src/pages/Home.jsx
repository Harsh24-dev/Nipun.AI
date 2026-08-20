import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Mic, Paperclip, Send, Clock, MessageSquare, MoreHorizontal, Pencil, Trash2, ArrowRight, Loader2 } from "lucide-react";
import NipunLogo from "@/components/nipun/NipunLogo";
import { useApp } from "@/lib/AppContext";
import { sessions as sessionsApi, query as queryApi } from "@/lib/api";
import { getGreeting } from "@/lib/i18n";
import moment from "moment";

const EXAMPLE_PROMPTS = [
  "PM-KISAN eligibility",
  "File an FIR online",
  "Today's wheat mandi price near me",
  "EMI on ₹5 lakh loan",
  "NCERT Class 10 Science help",
  "GST registration steps",
];

export default function Home() {
  const { user, profile, activeSessionId, setActiveSessionId } = useApp();
  const navigate = useNavigate();
  const [queryText, setQueryText] = useState("");
  const [recentSessions, setRecentSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [menuOpen, setMenuOpen] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [renameVal, setRenameVal] = useState("");
  const inputRef = useRef(null);

  const firstName = user?.name?.split(" ")[0] || "";
  const greeting = getGreeting(profile?.language || "en");

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    setSessionsLoading(true);
    try {
      const data = await sessionsApi.list(6, 0);
      setRecentSessions(Array.isArray(data) ? data : []);
    } catch {}
    setSessionsLoading(false);
  };

  const handleSubmit = async (text) => {
    const q = text || queryText;
    if (!q.trim()) return;
    setLoading(true);
    try {
      const res = await queryApi.send({ query: q.trim() });
      if (res?.session_id) {
        setActiveSessionId(res.session_id);
        navigate(`/workspace/${res.session_id}`);
      }
    } catch {
      navigate("/workspace");
    }
    setLoading(false);
  };

  const handleRename = async (id) => {
    if (!renameVal.trim()) return;
    try {
      await sessionsApi.update(id, { title: renameVal });
      setRecentSessions(prev => prev.map(s => s.id === id ? { ...s, title: renameVal } : s));
    } catch {}
    setRenaming(null);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this conversation? This will also remove uploaded documents for this session.")) return;
    try {
      await sessionsApi.delete(id);
      setRecentSessions(prev => prev.filter(s => s.id !== id));
    } catch {}
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4 relative motif-bg" style={{ background: "var(--background)" }}>
      {/* Top right: settings/profile */}
      <div className="absolute top-4 right-4">
        <button onClick={() => navigate("/settings")} className="p-2 rounded-lg text-sm hover:opacity-80" style={{ color: "var(--text-muted)" }}>
          Settings
        </button>
      </div>

      <div className="w-full max-w-2xl mx-auto flex flex-col items-center -mt-12">
        <NipunLogo size="xl" className="mb-6" />

        <p className="text-lg mb-8" style={{ color: "var(--text-secondary)" }}>
          {greeting}, {firstName}
        </p>

        <div className="w-full relative mb-6">
          <div className="flex items-center rounded-2xl border shadow-sm overflow-hidden transition-shadow focus-within:shadow-md"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
            <input
              ref={inputRef}
              value={queryText}
              onChange={e => setQueryText(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && handleSubmit()}
              placeholder="Ask anything…"
              className="flex-1 px-6 py-4 text-base bg-transparent outline-none"
              style={{ color: "var(--text)" }}
              disabled={loading}
            />
            <div className="flex items-center gap-1 pr-3">
              {profile?.voiceEnabled && (
                <button className="p-2 rounded-full hover:opacity-80 transition-opacity" style={{ color: "var(--text-muted)" }} aria-label="Voice input">
                  <Mic size={20} />
                </button>
              )}
              <button className="p-2 rounded-full hover:opacity-80 transition-opacity" style={{ color: "var(--text-muted)" }} aria-label="Attach file">
                <Paperclip size={18} />
              </button>
              <button onClick={() => handleSubmit()} disabled={!queryText.trim() || loading}
                className="p-2 rounded-full transition-all disabled:opacity-30"
                style={{ background: "var(--accent)", color: "var(--accent-text)" }} aria-label="Send">
                {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 justify-center mb-12">
          {EXAMPLE_PROMPTS.map(p => (
            <button key={p} onClick={() => { setQueryText(p); handleSubmit(p); }}
              className="px-3 py-1.5 rounded-full text-xs border transition-all hover:scale-[1.02]"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)", background: "var(--surface)" }}>
              {p}
            </button>
          ))}
        </div>

        <div className="w-full">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>Recent conversations</h3>
            <button onClick={() => navigate("/workspace")} className="text-xs hover:underline" style={{ color: "var(--accent)" }}>
              See all
            </button>
          </div>

          {sessionsLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 size={20} className="animate-spin" style={{ color: "var(--text-muted)" }} />
            </div>
          ) : recentSessions.length === 0 ? (
            <p className="text-center py-8 text-sm" style={{ color: "var(--text-muted)" }}>
              No conversations yet — ask something above to get started
            </p>
          ) : (
            <div className="grid sm:grid-cols-2 gap-2">
              {recentSessions.map(s => (
                <div key={s.id} className="group relative rounded-xl border p-3 cursor-pointer transition-all hover:shadow-sm"
                  style={{ background: "var(--surface)", borderColor: "var(--border)" }}
                  onClick={() => { setActiveSessionId(s.id); navigate(`/workspace/${s.id}`); }}>
                  {renaming === s.id ? (
                    <input value={renameVal} onChange={e => setRenameVal(e.target.value)}
                      onBlur={() => handleRename(s.id)} onKeyDown={e => e.key === "Enter" && handleRename(s.id)}
                      className="text-sm font-medium bg-transparent border-b outline-none w-full"
                      style={{ borderColor: "var(--accent)", color: "var(--text)" }}
                      autoFocus onClick={e => e.stopPropagation()} />
                  ) : (
                    <h4 className="text-sm font-medium truncate pr-8" style={{ color: "var(--text)" }}>
                      {s.title || "Untitled conversation"}
                    </h4>
                  )}
                  <div className="flex items-center gap-2 mt-1.5">
                    {s.language && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>{s.language}</span>}
                    {s.domain && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface-sunken)", color: "var(--text-muted)" }}>{s.domain}</span>}
                    <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{s.turn_count || 0} turns</span>
                    <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{moment(s.started_at).fromNow()}</span>
                  </div>
                  <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1" onClick={e => e.stopPropagation()}>
                    <button onClick={() => { setRenaming(s.id); setRenameVal(s.title || ""); }} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Rename">
                      <Pencil size={12} />
                    </button>
                    <button onClick={() => handleDelete(s.id)} className="p-1 rounded hover:opacity-80" style={{ color: "var(--destructive)" }} aria-label="Delete">
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}