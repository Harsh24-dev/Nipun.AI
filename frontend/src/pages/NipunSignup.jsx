import React, { useState } from "react";
import { Link } from "react-router-dom";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import AuthShell from "@/components/nipun/AuthShell";
import { auth as authApi } from "@/lib/api";
import { useApp } from "@/lib/AppContext";

export default function NipunSignup() {
  const { setToken, setUser } = useApp();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name || !email || !password || !confirm) return setError("Please fill in all fields");
    if (password.length < 6) return setError("Password must be at least 6 characters");
    if (password !== confirm) return setError("Passwords do not match");
    setError("");
    setLoading(true);
    try {
      // OTP disabled — signup directly logs in
      const res = await authApi.signup({ name, email, password });
      setToken(res.token || res.access_token);
      setUser(res.user);
      window.location.href = "/onboarding";
    } catch (err) {
      setError(err.status === 409 ? "An account with this email already exists." : (err.message || "Failed to connect to backend"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Create your account">

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg text-sm" style={{ background: "rgba(220,38,38,0.1)", color: "var(--destructive)" }}>{error}</div>
        )}
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Full name</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)}
            className="w-full px-4 py-3 rounded-lg text-sm border outline-none"
            style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
            placeholder="Your name" autoComplete="name" />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)}
            className="w-full px-4 py-3 rounded-lg text-sm border outline-none"
            style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
            placeholder="you@example.com" autoComplete="email" />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Password</label>
          <div className="relative">
            <input type={showPw ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)}
              className="w-full px-4 py-3 pr-10 rounded-lg text-sm border outline-none"
              style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
              placeholder="At least 6 characters" autoComplete="new-password" />
            <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 p-1" onClick={() => setShowPw(!showPw)}
              style={{ color: "var(--text-muted)" }}>
              {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Confirm password</label>
          <input type={showPw ? "text" : "password"} value={confirm} onChange={e => setConfirm(e.target.value)}
            className="w-full px-4 py-3 rounded-lg text-sm border outline-none"
            style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
            placeholder="Repeat password" autoComplete="new-password" />
        </div>
        <button type="submit" disabled={loading}
          className="w-full py-3 rounded-lg text-sm font-medium disabled:opacity-50 flex items-center justify-center gap-2"
          style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
          {loading && <Loader2 size={16} className="animate-spin" />}
          Create account
        </button>
        <p className="text-center text-sm" style={{ color: "var(--text-muted)" }}>
          Already have an account? <Link to="/login" className="font-medium hover:underline" style={{ color: "var(--accent)" }}>Log in</Link>
        </p>
      </form>
    </AuthShell>
  );
}