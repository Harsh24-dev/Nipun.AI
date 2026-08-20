import React, { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Users, MessageSquare, Activity, BarChart3, ArrowLeft, Loader2 } from "lucide-react";
import { admin as adminApi, health as healthApi } from "@/lib/api";
import NipunLogo from "@/components/nipun/NipunLogo";

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [healthData, setHealthData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [u, h] = await Promise.all([
        adminApi.getUsers({ limit: 1000 }).catch(() => []),
        healthApi.check().catch(() => null),
      ]);
      setUsers(Array.isArray(u) ? u : []);
      setHealthData(h);
    } catch {}
    setLoading(false);
  };

  const totalUsers = users.length;
  const activeUsers = users.filter(u => u.is_active !== false).length;

  const kpis = [
    { label: "Total Users", value: totalUsers, icon: Users, color: "var(--accent)" },
    { label: "Active Users", value: activeUsers, icon: Users, color: "var(--success)" },
    { label: "Sessions Today", value: "—", icon: MessageSquare, color: "#3B82F6" },
    { label: "Queries Today", value: "—", icon: Activity, color: "#8B5CF6" },
  ];

  return (
    <div className="min-h-screen" style={{ background: "var(--background)" }}>
      <div className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate("/home")} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }}>
              <ArrowLeft size={18} />
            </button>
            <h1 className="text-lg font-heading font-semibold" style={{ color: "var(--text)" }}>Admin Dashboard</h1>
          </div>
          <div className="flex gap-2 text-xs">
            <Link to="/admin/users" className="px-3 py-1.5 rounded-lg border hover:opacity-80" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>Users</Link>
            <Link to="/admin/monitoring" className="px-3 py-1.5 rounded-lg border hover:opacity-80" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>Monitoring</Link>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-6">
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 size={24} className="animate-spin" style={{ color: "var(--text-muted)" }} /></div>
        ) : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
              {kpis.map((k, i) => (
                <div key={i} className="p-5 rounded-xl border" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                  <div className="flex items-center gap-2 mb-2">
                    <k.icon size={16} style={{ color: k.color }} />
                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>{k.label}</span>
                  </div>
                  <span className="text-2xl font-bold" style={{ color: "var(--text)" }}>{k.value}</span>
                </div>
              ))}
            </div>

            {healthData && (
              <div className="rounded-xl border p-5 mb-8" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>System Health</h3>
                <div className="flex gap-4 flex-wrap">
                  {Object.entries(healthData).filter(([k]) => k !== "status").map(([k, v]) => (
                    <div key={k} className="text-xs">
                      <span className="font-medium capitalize">{k}: </span>
                      <span style={{ color: v?.status === "ok" || v === "ok" ? "var(--success)" : "var(--warning)" }}>
                        {typeof v === "object" ? v.status || JSON.stringify(v) : v}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Chart placeholders */}
            <div className="grid md:grid-cols-2 gap-4">
              {["Queries Over Time", "By Domain", "By Language", "By Status"].map(title => (
                <div key={title} className="rounded-xl border p-5" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                  <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text)" }}>{title}</h3>
                  <div className="h-32 flex items-center justify-center rounded-lg" style={{ background: "var(--surface-sunken)" }}>
                    <div className="text-center">
                      <BarChart3 size={24} className="mx-auto mb-1" style={{ color: "var(--text-muted)", opacity: 0.3 }} />
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>Data will appear when metrics endpoint is wired</span>
                    </div>
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