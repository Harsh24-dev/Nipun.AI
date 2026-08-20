import React, { useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, ArrowLeft } from "lucide-react";
import AuthShell from "@/components/nipun/AuthShell";
import { auth as authApi } from "@/lib/api";

export default function NipunResetPassword() {
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !newPassword) return setError("Please fill in all fields");
    if (newPassword.length < 6) return setError("Password must be at least 6 characters");
    setError("");
    setLoading(true);
    try {
      await authApi.resetPassword({ email, new_password: newPassword });
      setSuccess(true);
    } catch (err) {
      setError(err.status === 404 ? "No account found for that email." : (err.message || "Something went wrong"));
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <AuthShell title="Password reset">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full mx-auto mb-4 flex items-center justify-center" style={{ background: "var(--accent-subtle)" }}>
            <span className="text-xl">✓</span>
          </div>
          <p className="mb-6" style={{ color: "var(--text-secondary)" }}>Your password has been updated. You can now log in.</p>
          <Link to="/login" className="inline-flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-medium" style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
            Go to login
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Reset password">
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg text-sm" style={{ background: "rgba(220,38,38,0.1)", color: "var(--destructive)" }}>
            {error}
          </div>
        )}
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)}
            className="w-full px-4 py-3 rounded-lg text-sm border outline-none focus:ring-2"
            style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }}
            placeholder="you@example.com" />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>New password</label>
          <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)}
            className="w-full px-4 py-3 rounded-lg text-sm border outline-none focus:ring-2"
            style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }}
            placeholder="At least 6 characters" />
        </div>
        <button type="submit" disabled={loading}
          className="w-full py-3 rounded-lg text-sm font-medium transition-all hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
          style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : null}
          Reset password
        </button>
        <Link to="/login" className="flex items-center gap-1 text-sm justify-center" style={{ color: "var(--text-muted)" }}>
          <ArrowLeft size={14} /> Back to login
        </Link>
      </form>
    </AuthShell>
  );
}