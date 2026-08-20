import React, { useState, useEffect } from "react";
import { X, FileText, Wrench, Zap, Upload, Loader2, Trash2, AlertTriangle } from "lucide-react";
import { documents as docsApi, tools as toolsApi, tasks as tasksApi } from "@/lib/api";
import { toast } from "@/components/ui/use-toast";

export default function RightRail({ open, onClose, activeTab: initialTab, sessionId }) {
  const [tab, setTab] = useState(initialTab || "documents");
  const [docs, setDocs] = useState([]);
  const [toolsList, setToolsList] = useState([]);
  const [tasksList, setTasksList] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => { if (open) loadData(); }, [open, tab]);

  const loadData = async () => {
    setLoading(true);
    try {
      if (tab === "documents") { const d = await docsApi.list(); setDocs(Array.isArray(d) ? d : []); }
      else if (tab === "tools") { const t = await toolsApi.list(); setToolsList(Array.isArray(t) ? t : []); }
      else if (tab === "tasks") { const t = await tasksApi.list(); setTasksList(Array.isArray(t) ? t : []); }
    } catch (err) {
      console.error(`Failed to load ${tab}`, err);
      toast({ variant: "destructive", title: `Couldn't load ${tab}`, description: err.message || "Please try again." });
    }
    setLoading(false);
  };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    if (sessionId) fd.append("session_id", sessionId);
    setLoading(true);
    try {
      await docsApi.upload(fd);
      loadData();
    } catch (err) {
      alert(err.message || "Upload failed");
    }
    setLoading(false);
  };

  const handleDeleteDoc = async (id) => {
    try {
      await docsApi.delete(id);
      loadData();
    } catch (err) {
      console.error("Failed to delete document", err);
      toast({ variant: "destructive", title: "Couldn't delete document", description: err.message || "Please try again." });
    }
  };

  if (!open) return null;

  const tabs = [
    { id: "documents", label: "Documents", icon: FileText },
    { id: "tools", label: "Tools", icon: Wrench },
    { id: "tasks", label: "Tasks", icon: Zap },
  ];

  return (
    <div className="w-72 border-l flex flex-col h-full flex-shrink-0"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between p-3 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="flex gap-1">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors"
              style={{
                background: tab === t.id ? "var(--accent-subtle)" : "transparent",
                color: tab === t.id ? "var(--accent)" : "var(--text-muted)"
              }}>
              <t.icon size={10} /> {t.label}
            </button>
          ))}
        </div>
        <button onClick={onClose} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }}>
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 size={16} className="animate-spin" style={{ color: "var(--text-muted)" }} />
          </div>
        ) : tab === "documents" ? (
          <div>
            <label className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border cursor-pointer hover:opacity-80 mb-3"
              style={{ borderColor: "var(--border)", color: "var(--accent)" }}>
              <Upload size={12} /> Upload document
              <input type="file" className="hidden" onChange={handleUpload} />
            </label>
            {docs.length === 0 ? (
              <p className="text-xs text-center py-4" style={{ color: "var(--text-muted)" }}>No documents uploaded</p>
            ) : (
              <div className="space-y-1">
                {docs.map(d => (
                  <div key={d.document_id || d.id} className="flex items-center gap-2 p-2 rounded-lg text-xs group"
                    style={{ background: "var(--surface-sunken)" }}>
                    <FileText size={12} style={{ color: "var(--accent)" }} />
                    <span className="flex-1 truncate" style={{ color: "var(--text)" }}>{d.title || "Untitled"}</span>
                    <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{d.status}</span>
                    <button onClick={() => handleDeleteDoc(d.document_id || d.id)}
                      className="p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                      style={{ color: "var(--destructive)" }}>
                      <Trash2 size={10} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : tab === "tools" ? (
          <div className="space-y-2">
            {toolsList.length === 0 ? (
              <p className="text-xs text-center py-4" style={{ color: "var(--text-muted)" }}>No tools available</p>
            ) : toolsList.map((t, i) => (
              <div key={i} className="p-2 rounded-lg text-xs" style={{ background: "var(--surface-sunken)" }}>
                <span className="font-medium" style={{ color: "var(--text)" }}>{t.name}</span>
                {t.read_only && <span className="text-[10px] ml-1" style={{ color: "var(--text-muted)" }}>(read-only)</span>}
                <p className="mt-0.5" style={{ color: "var(--text-muted)" }}>{t.description}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {tasksList.length === 0 ? (
              <p className="text-xs text-center py-4" style={{ color: "var(--text-muted)" }}>No tasks available</p>
            ) : tasksList.map((t, i) => (
              <div key={i} className="p-2 rounded-lg text-xs" style={{ background: "var(--surface-sunken)" }}>
                <span className="font-medium" style={{ color: "var(--text)" }}>{t.name || t.action}</span>
                <p className="mt-0.5" style={{ color: "var(--text-muted)" }}>{t.description}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}