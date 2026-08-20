import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Activity, Loader2, CheckCircle, AlertTriangle, XCircle, RefreshCw } from "lucide-react";
import { health as healthApi } from "@/lib/api";

const METRIC_PANELS = [
  { title: "Queries by Domain", desc: "Distribution across legal, farming, schemes, etc." },
  { title: "Queries by Language", desc: "Hindi, English, Tamil, Telugu, and more" },
  { title: "Queries by Status", desc: "Success, failed, abstained, rate-limited" },
  { title: "LLM Tokens/Latency", desc: "Token usage and response time" },
  { title: "Retrieval Latency", desc: "RAG pipeline response times" },
  { title: "Cache Hit Rate", desc: "Embedding and response cache performance" },
  { title: "Agent Calls", desc: "Multi-agent task distribution" },
  { title: "Error Rate", desc: "5xx and failed queries" },
];

const ALERT_RULES = [
  { rule: "p99 latency > 3s", status: "ok" },
  { rule: "Error rate > 5%", status: "ok" },
  { rule: "Queue depth > threshold", status: "ok" },
  { rule: "LLM errors spike", status: "ok" },
  { rule: "Slow retrieval (> 2s)", status: "ok" },
];

export default function AdminMonitoring() {
  const navigate = useNavigate();
  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadHealth = async () => {
    setLoading(true);
    try {
      const data = await healthApi.check();
      setHealthData(data);
    } catch {}
    setLoading(false);
  };

  useEffect(() => { loadHealth(); }, []);

  const getStatusIcon = (status) => {
    if (status === "ok" || status === "healthy") return <CheckCircle size={14} style={{ color: "var(--success)" }} />;
    if (status === "degraded") return <AlertTriangle size={14} style={{ color: "var(--warning)" }} />;
    return <XCircle size={14} style={{ color: "var(--destructive)" }} />;
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--background)" }}>
      <div className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate("/admin")} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }}><ArrowLeft size={18} /></button>
            <h1 className="text-lg font-heading font-semibold" style={{ color: "var(--text)" }}>Monitoring</h1>
          </div>
          <button onClick={loadHealth} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs border hover:opacity-80"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-6">
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 size={24} className="animate-spin" style={{ color: "var(--text-muted)" }} /></div>
        ) : (
          <>
            <div className="rounded-xl border p-5 mb-6" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
              <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>System Health</h3>
              {healthData ? (
                <div className="grid sm:grid-cols-3 gap-4">
                  {Object.entries(healthData).filter(([k]) => k !== "status").map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2 p-3 rounded-lg" style={{ background: "var(--surface-sunken)" }}>
                      {getStatusIcon(typeof v === "object" ? v.status : v)}
                      <div>
                        <span className="text-sm font-medium capitalize">{k}</span>
                        {typeof v === "object" && v.latency_ms && (
                          <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>{v.latency_ms}ms</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>Health endpoint not available</p>
              )}
            </div>

            <div className="rounded-xl border p-5 mb-6" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
              <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>Alert Rules</h3>
              <div className="space-y-2">
                {ALERT_RULES.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    {getStatusIcon(a.status)}
                    <span style={{ color: "var(--text)" }}>{a.rule}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              {METRIC_PANELS.map((p, i) => (
                <div key={i} className="rounded-xl border p-5" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                  <h3 className="text-sm font-medium mb-1" style={{ color: "var(--text)" }}>{p.title}</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>{p.desc}</p>
                  <div className="h-24 flex items-center justify-center rounded-lg" style={{ background: "var(--surface-sunken)" }}>
                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>Pending metrics endpoint</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}