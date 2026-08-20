import React, { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Plus, Search, MessageSquare, Pencil, Trash2, ChevronLeft, Home } from "lucide-react";
import { sessions as sessionsApi } from "@/lib/api";
import { toast } from "@/components/ui/use-toast";
import { useApp } from "@/lib/AppContext";
import moment from "moment";

export default function WorkspaceSidebar({ collapsed, onToggle }) {
  const navigate = useNavigate();
  const { sessionId } = useParams();
  const { setActiveSessionId } = useApp();
  const [sessions, setSessions] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [renaming, setRenaming] = useState(null);
  const [renameVal, setRenameVal] = useState("");

  // Reload the list whenever the active session changes so a newly-created conversation
  // (persisted on its first turn) shows up in "recent conversations" without a manual refresh.
  useEffect(() => { loadSessions(); }, [sessionId]);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await sessionsApi.list(50, 0);
      setSessions(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("Failed to load conversations", err);
      toast({ variant: "destructive", title: "Couldn't load conversations", description: err.message || "Please try again." });
    }
    setLoading(false);
  };

  const handleNew = () => {
    setActiveSessionId(null);
    navigate("/workspace");
  };

  const handleSelect = (id) => {
    setActiveSessionId(id);
    navigate(`/workspace/${id}`);
  };

  const handleRename = async (id) => {
    if (!renameVal.trim()) return;
    try {
      await sessionsApi.update(id, { title: renameVal });
      setSessions(prev => prev.map(s => s.id === id ? { ...s, title: renameVal } : s));
    } catch (err) {
      console.error("Failed to rename conversation", err);
      toast({ variant: "destructive", title: "Couldn't rename conversation", description: err.message || "Please try again." });
    }
    setRenaming(null);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this conversation? This also removes uploaded docs.")) return;
    try {
      await sessionsApi.delete(id);
      setSessions(prev => prev.filter(s => s.id !== id));
      if (sessionId === id) navigate("/workspace");
    } catch (err) {
      console.error("Failed to delete conversation", err);
      toast({ variant: "destructive", title: "Couldn't delete conversation", description: err.message || "Please try again." });
    }
  };

  const filtered = sessions.filter(s =>
    !search || (s.title || "").toLowerCase().includes(search.toLowerCase())
  );

  if (collapsed) {
    return (
      <div className="w-12 flex flex-col items-center py-3 gap-2 border-r flex-shrink-0"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        <button onClick={handleNew} className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--accent)" }} aria-label="New chat">
          <Plus size={18} />
        </button>
        <button onClick={() => navigate("/home")} className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Home">
          <Home size={18} />
        </button>
        <button onClick={onToggle} className="p-2 rounded-lg hover:opacity-80 mt-auto" style={{ color: "var(--text-muted)" }} aria-label="Expand sidebar">
          <MessageSquare size={18} />
        </button>
      </div>
    );
  }

  return (
    <div className="w-64 flex flex-col border-r flex-shrink-0 h-full"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <div className="p-3 flex items-center gap-2">
        <button onClick={handleNew} className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all hover:opacity-90"
          style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
          <Plus size={14} /> New chat
        </button>
        <button onClick={onToggle} className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Collapse">
          <ChevronLeft size={16} />
        </button>
      </div>

      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg border" style={{ borderColor: "var(--border)", background: "var(--surface-sunken)" }}>
          <Search size={12} style={{ color: "var(--text-muted)" }} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search conversations…"
            className="flex-1 text-xs bg-transparent outline-none" style={{ color: "var(--text)" }} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="w-4 h-4 border-2 rounded-full animate-spin" style={{ borderColor: "var(--border)", borderTopColor: "var(--accent)" }} />
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-center py-4" style={{ color: "var(--text-muted)" }}>No conversations</p>
        ) : (
          <div className="space-y-0.5">
            {filtered.map(s => (
              <div key={s.id}
                className="group flex items-center gap-2 px-2 py-2 rounded-lg cursor-pointer transition-colors"
                style={{
                  background: sessionId === s.id ? "var(--accent-subtle)" : "transparent",
                }}
                onClick={() => handleSelect(s.id)}>
                <div className="flex-1 min-w-0">
                  {renaming === s.id ? (
                    <input value={renameVal} onChange={e => setRenameVal(e.target.value)}
                      onBlur={() => handleRename(s.id)} onKeyDown={e => e.key === "Enter" && handleRename(s.id)}
                      className="text-xs bg-transparent border-b outline-none w-full" style={{ borderColor: "var(--accent)", color: "var(--text)" }}
                      autoFocus onClick={e => e.stopPropagation()} />
                  ) : (
                    <span className="text-xs truncate block" style={{ color: "var(--text)" }}>
                      {s.title || "Untitled"}
                    </span>
                  )}
                  <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                    {moment(s.started_at).fromNow()}
                  </span>
                </div>
                <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                  <button onClick={() => { setRenaming(s.id); setRenameVal(s.title || ""); }} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }}>
                    <Pencil size={10} />
                  </button>
                  <button onClick={() => handleDelete(s.id)} className="p-1 rounded hover:opacity-80" style={{ color: "var(--destructive)" }}>
                    <Trash2 size={10} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="p-3 border-t" style={{ borderColor: "var(--border)" }}>
        <button onClick={() => navigate("/home")} className="flex items-center gap-2 text-xs w-full px-2 py-1.5 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }}>
          <Home size={14} /> Home
        </button>
      </div>
    </div>
  );
}