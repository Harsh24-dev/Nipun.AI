import React, { useState } from "react";
import { Link } from "react-router-dom";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import AuthShell from "@/components/nipun/AuthShell";
import { auth as authApi } from "@/lib/api";
import { useApp } from "@/lib/AppContext";

export default function NipunLogin() {
  const { setToken, setUser } = useApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) return setError("Please fill in all fields");
    setError("");
    setLoading(true);
    try {
      const res = await authApi.login({ email, password });
      setToken(res.token || res.access_token);
      setUser(res.user);
      const onboarded = localStorage.getItem("nipun_onboarded_" + res.user?.id);
      window.location.href = onboarded ? "/home" : "/onboarding";
    } catch (err) {
      setError(err.status === 401 ? "Invalid email or password." : (err.message || "Failed to connect to backend"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Welcome back">

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg text-sm" style={{ background: "rgba(220,38,38,0.1)", color: "var(--destructive)" }}>
            {error}
          </div>
        )}
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Email</label>
          <input
            type="email" value={email} onChange={e => setEmail(e.target.value)}
            className="w-full px-4 py-3 rounded-lg text-sm border outline-none"
            style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
            placeholder="you@example.com" autoComplete="email"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Password</label>
          <div className="relative">
            <input
              type={showPw ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)}
              className="w-full px-4 py-3 pr-10 rounded-lg text-sm border outline-none"
              style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
              placeholder="••••••••" autoComplete="current-password"
            />
            <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 p-1" onClick={() => setShowPw(!showPw)}
              style={{ color: "var(--text-muted)" }}>
              {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <div className="text-right">
          <Link to="/reset-password" className="text-sm hover:underline" style={{ color: "var(--accent)" }}>Forgot password?</Link>
        </div>
        <button type="submit" disabled={loading}
          className="w-full py-3 rounded-lg text-sm font-medium transition-all hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
          style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
          {loading && <Loader2 size={16} className="animate-spin" />}
          Log in
        </button>
        <p className="text-center text-sm" style={{ color: "var(--text-muted)" }}>
          Don't have an account? <Link to="/signup" className="font-medium hover:underline" style={{ color: "var(--accent)" }}>Sign up</Link>
        </p>
      </form>
    </AuthShell>
  );
}