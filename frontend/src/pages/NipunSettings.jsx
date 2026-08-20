import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Loader2, Check, Mic } from "lucide-react";
import { useApp } from "@/lib/AppContext";
import { LANGUAGES } from "@/lib/i18n";
import { STATES_UTS } from "@/lib/theme/regions";
import { presets } from "@/lib/theme/presets";
import { palettes, lightPalettes, darkPalettes } from "@/lib/theme/palettes";
import { motifs } from "@/lib/theme/motifs";
import NipunLogo from "@/components/nipun/NipunLogo";

const TABS = ["Profile", "Appearance", "Documents", "Account"];

export default function NipunSettings() {
  const navigate = useNavigate();
  const { user, setUser, profile, updateProfileRemote, clearAuth } = useApp();
  const [tab, setTab] = useState("Profile");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Profile form
  const [form, setForm] = useState({
    name: user?.name || "",
    language: profile?.language || "en",
    state: profile?.state || "",
    district: profile?.district || "",
    occupation: profile?.occupation || "",
    bio: profile?.bio || "",
    interests: profile?.interests?.join(", ") || "",
    ai_model: profile?.ai_model || "auto",
  });

  const setField = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const saveProfile = async () => {
    setSaving(true);
    const interests = form.interests
      ? form.interests.split(",").map(s => s.trim()).filter(Boolean)
      : [];
    await updateProfileRemote({
      name: form.name,
      language: form.language,
      state: form.state,
      district: form.district,
      occupation: form.occupation,
      bio: form.bio,
      interests,
      ai_model: form.ai_model,
    });
    if (form.name && user) setUser({ ...user, name: form.name });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    setSaving(false);
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--background)" }}>
      <div className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="p-1 rounded hover:opacity-80" style={{ color: "var(--text-muted)" }}>
            <ArrowLeft size={18} />
          </button>
          <h1 className="text-lg font-heading font-semibold" style={{ color: "var(--text)" }}>Settings</h1>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 py-6 flex flex-col md:flex-row gap-6">
        <div className="flex md:flex-col gap-1 md:w-48 flex-shrink-0">
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)}
              className="px-3 py-2 rounded-lg text-sm text-left transition-colors"
              style={{
                background: tab === t ? "var(--accent-subtle)" : "transparent",
                color: tab === t ? "var(--accent)" : "var(--text-secondary)",
                fontWeight: tab === t ? 600 : 400,
              }}>
              {t}
            </button>
          ))}
        </div>

        <div className="flex-1">
          {tab === "Profile" && (
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Name</label>
                <input value={form.name} onChange={e => setField("name", e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg text-sm border outline-none focus:ring-2"
                  style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                  Preferred language
                  <span className="font-normal text-xs ml-1" style={{ color: "var(--text-muted)" }}>— your default UI; answers follow whatever language you ask in</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  {LANGUAGES.map(l => (
                    <button key={l.code} onClick={() => setField("language", l.code)}
                      className="px-3 py-1.5 rounded-lg text-xs border"
                      style={{ borderColor: form.language === l.code ? "var(--accent)" : "var(--border)", background: form.language === l.code ? "var(--accent-subtle)" : "transparent" }}>
                      {l.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>State</label>
                  <select value={form.state} onChange={e => setField("state", e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg text-sm border outline-none"
                    style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}>
                    <option value="">Select</option>
                    {STATES_UTS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>District</label>
                  <input value={form.district} onChange={e => setField("district", e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg text-sm border outline-none"
                    style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Occupation</label>
                <input value={form.occupation} onChange={e => setField("occupation", e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg text-sm border outline-none"
                  style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Bio</label>
                <textarea value={form.bio} onChange={e => setField("bio", e.target.value)} rows={3}
                  className="w-full px-3 py-2.5 rounded-lg text-sm border outline-none resize-none"
                  style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                  Interests <span className="font-normal text-xs" style={{ color: "var(--text-muted)" }}>— comma-separated</span>
                </label>
                <input value={form.interests} onChange={e => setField("interests", e.target.value)} placeholder="farming, legal, education"
                  className="w-full px-3 py-2.5 rounded-lg text-sm border outline-none"
                  style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Answer style</label>
                <div className="flex gap-2">
                  {["auto", "speed", "deep"].map(m => (
                    <button key={m} onClick={() => setField("ai_model", m)}
                      className="px-3 py-1.5 rounded-lg text-xs border capitalize"
                      style={{ borderColor: form.ai_model === m ? "var(--accent)" : "var(--border)", background: form.ai_model === m ? "var(--accent-subtle)" : "transparent" }}>
                      {m === "deep" ? "Deep Reasoning" : m}
                    </button>
                  ))}
                </div>
              </div>
              <button onClick={saveProfile} disabled={saving}
                className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium"
                style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                {saving ? <Loader2 size={14} className="animate-spin" /> : saved ? <Check size={14} /> : null}
                {saved ? "Saved!" : "Save profile"}
              </button>
            </div>
          )}

          {tab === "Appearance" && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>Preset</h3>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {Object.values(presets).map(p => (
                    <button key={p.id} onClick={() => updateProfileRemote({ uiPreset: p.id, theme: p.defaultPalette })}
                      className="p-3 rounded-xl border text-left transition-all"
                      style={{ borderColor: profile.uiPreset === p.id ? "var(--accent)" : "var(--border)", background: profile.uiPreset === p.id ? "var(--accent-subtle)" : "var(--surface)" }}>
                      <div className="flex gap-1 mb-2">
                        {p.swatch.map((c, i) => <div key={i} className="w-4 h-4 rounded-full" style={{ background: c }} />)}
                      </div>
                      <span className="text-sm font-medium">{p.name}</span>
                      <span className="block text-xs" style={{ color: "var(--text-muted)" }}>{p.subtitle}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text)" }}>Light palettes</h3>
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 mb-4">
                  {lightPalettes.map(p => (
                    <button key={p.id} onClick={() => updateProfileRemote({ theme: p.id })}
                      className="p-2 rounded-lg border text-xs text-center transition-all"
                      style={{ borderColor: profile.theme === p.id ? "var(--accent)" : "var(--border)" }}>
                      <div className="flex gap-0.5 justify-center mb-1">
                        {p.swatch.map((c, i) => <div key={i} className="w-3 h-3 rounded-full" style={{ background: c }} />)}
                      </div>
                      {p.name}
                    </button>
                  ))}
                </div>
                <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text)" }}>Dark palettes</h3>
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {darkPalettes.map(p => (
                    <button key={p.id} onClick={() => updateProfileRemote({ theme: p.id })}
                      className="p-2 rounded-lg border text-xs text-center transition-all"
                      style={{ borderColor: profile.theme === p.id ? "var(--accent)" : "var(--border)" }}>
                      <div className="flex gap-0.5 justify-center mb-1">
                        {p.swatch.map((c, i) => <div key={i} className="w-3 h-3 rounded-full" style={{ background: c }} />)}
                      </div>
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium mb-2" style={{ color: "var(--text)" }}>Cultural motif</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {Object.values(motifs).map(m => (
                    <button key={m.id} onClick={() => updateProfileRemote({ motif: m.id })}
                      className="p-2 rounded-lg border text-xs text-center transition-all"
                      style={{ borderColor: profile.motif === m.id ? "var(--accent)" : "var(--border)", background: profile.motif === m.id ? "var(--accent-subtle)" : "transparent" }}>
                      {m.name}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="text-sm font-medium" style={{ color: "var(--text)" }}>Accessibility</h3>
                <div className="flex items-center gap-3">
                  <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Text size</span>
                  {["S", "M", "L", "XL"].map(s => (
                    <button key={s} onClick={() => updateProfileRemote({ textScale: s })}
                      className="px-3 py-1.5 rounded text-xs border font-medium"
                      style={{ borderColor: profile.textScale === s ? "var(--accent)" : "var(--border)", background: profile.textScale === s ? "var(--accent-subtle)" : "transparent" }}>
                      {s}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={profile.highContrast || false} onChange={e => updateProfileRemote({ highContrast: e.target.checked })} className="rounded" />
                  <span className="text-sm">High contrast</span>
                </label>
                <label className="flex items-center gap-3 cursor-pointer">
                  <Mic size={16} style={{ color: "var(--text-muted)" }} />
                  <input type="checkbox" checked={profile.voiceEnabled || false} onChange={e => updateProfileRemote({ voiceEnabled: e.target.checked })} className="rounded" />
                  <span className="text-sm">Voice (speak & listen)</span>
                </label>
              </div>
            </div>
          )}

          {tab === "Documents" && (
            <div>
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>Manage your uploaded documents from the workspace Documents panel.</p>
            </div>
          )}

          {tab === "Account" && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>Email</label>
                <p className="text-sm" style={{ color: "var(--text)" }}>{user?.email}</p>
              </div>
              <button onClick={() => navigate("/reset-password")} className="text-sm hover:underline" style={{ color: "var(--accent)" }}>
                Reset password
              </button>
              <div className="pt-4 border-t" style={{ borderColor: "var(--border)" }}>
                <button onClick={() => { clearAuth(); navigate("/login"); }}
                  className="px-4 py-2 rounded-lg text-sm border"
                  style={{ borderColor: "var(--destructive)", color: "var(--destructive)" }}>
                  Log out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}