import React, { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight, ChevronLeft, Check, Mic } from "lucide-react";
import NipunLogo from "@/components/nipun/NipunLogo";
import { useApp } from "@/lib/AppContext";
import { LANGUAGES } from "@/lib/i18n";
import { STATES_UTS, getRegionForState, REGION_PALETTE_MAP } from "@/lib/theme/regions";
import { presets, AGE_PRESET_MAP, GENDER_PALETTE_NUDGE } from "@/lib/theme/presets";
import { palettes } from "@/lib/theme/palettes";
import { motifs, REGION_MOTIF_MAP } from "@/lib/theme/motifs";

const AGE_GROUPS = ["Under 13", "13-17", "18-29", "30-45", "46-60", "60+"];
const GENDERS = ["Female", "Male", "Non-binary", "Prefer not to say"];
const ANSWER_STYLES = [
  { value: "auto", label: "Auto", desc: "Let the system decide" },
  { value: "speed", label: "Speed", desc: "Quick, concise answers" },
  { value: "deep", label: "Deep Reasoning", desc: "Thorough, detailed analysis" },
];
// Quick-fill roles — the user can also type their own (e.g. "AI/ML student", "Software Engineer,
// 5 yrs", "founder"). This drives how tailored the answers are, so it's front-and-centre.
const ROLE_CHIPS = [
  "Student", "College student", "Working professional", "Business owner / founder",
  "Farmer", "Job seeker", "Government employee", "Teacher", "Healthcare worker",
  "Homemaker", "Retired",
];
// What the user wants help with — feeds topic personalization + which domains to lean into.
const INTEREST_OPTIONS = [
  "Studies & exams", "Career & jobs", "Re-skilling & new skills", "Coding & tech",
  "Government schemes", "Finance & banking", "Farming", "Health info", "Legal help",
  "Documents & ID", "Travel", "Business", "Research & papers", "General knowledge",
];

const STEPS = ["You", "Location", "Age group", "About you", "Interests", "Languages", "Your look"];

export default function Onboarding() {
  const { user, profile, setUser, updateProfileRemote, setOnboarded } = useApp();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);

  // Wizard data — prefilled from any existing profile so returning/editing users keep their info.
  const [data, setData] = useState({
    name: user?.name || profile?.name || "",
    language: profile?.language || "hi",
    state: profile?.state || "",
    district: profile?.district || "",
    ageBand: profile?.ageBand || "",
    gender: profile?.gender || "",
    occupation: profile?.occupation || "",
    interests: profile?.interests || [],
    answerStyle: profile?.ai_model || "auto",
    languagesKnown: profile?.languagesKnown || ["hi", "en"],
    uiPreset: profile?.uiPreset || "sampann",
    theme: profile?.theme || "saffron",
    motif: profile?.motif || "minimal",
    textScale: profile?.textScale || "M",
    highContrast: profile?.highContrast || false,
    voiceEnabled: profile?.voiceEnabled || false,
  });

  const set = (k, v) => setData(prev => ({ ...prev, [k]: v }));
  const region = data.state ? getRegionForState(data.state) : "north";

  // Suggested looks
  const suggestedPresets = useMemo(() => {
    const agePresets = AGE_PRESET_MAP[data.ageBand] || ["sampann", "nova", "shaant"];
    return agePresets.map(id => presets[id]);
  }, [data.ageBand]);

  const [showAllLooks, setShowAllLooks] = useState(false);

  // Keep onboarding QUICK: only a name is required to start — everything else is optional and
  // can be filled later (in Settings, or learned from conversation). So the user is never blocked.
  const canNext = () => {
    if (step === 0) return !!data.name;
    return true;
  };

  const finish = async () => {
    setSaving(true);
    await updateProfileRemote({
      onboarded: true,
      name: data.name,
      language: data.language,
      state: data.state,
      district: data.district || "",
      occupation: data.occupation || "",
      ai_model: data.answerStyle,
      theme: data.theme,
      uiPreset: data.uiPreset,
      motif: data.motif,
      textScale: data.textScale,
      highContrast: data.highContrast,
      voiceEnabled: data.voiceEnabled,
      ageBand: data.ageBand,
      gender: data.gender,
      languagesKnown: data.languagesKnown,
      interests: data.interests || [],
    });
    if (data.name && user) setUser({ ...user, name: data.name });
    setOnboarded();
    setSaving(false);
    navigate("/home");
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: "var(--background)" }}>
      <div className="w-full max-w-2xl">
        <div className="text-center mb-8">
          <NipunLogo size="md" />
        </div>

        <div className="flex items-center gap-1 mb-8 max-w-md mx-auto">
          {STEPS.map((s, i) => (
            <div key={i} className="flex-1 flex flex-col items-center">
              <div className="h-1.5 w-full rounded-full mb-1.5 transition-all" style={{ background: i <= step ? "var(--accent)" : "var(--border)" }} />
              <span className="text-[10px] hidden sm:block" style={{ color: i <= step ? "var(--accent)" : "var(--text-muted)" }}>{s}</span>
            </div>
          ))}
        </div>

        <div className="rounded-2xl border p-6 sm:p-8" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
          {/* Step 0: You */}
          {step === 0 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">Tell us about you</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>Your name and preferred language</p>
              <div className="mb-5">
                <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>Name</label>
                <input value={data.name} onChange={e => set("name", e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm border outline-none focus:ring-2"
                  style={{ background: "var(--surface-sunken)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>Preferred language</label>
                <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>Your default — answers still follow whatever language you ask in.</p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {LANGUAGES.map(l => (
                    <button key={l.code} onClick={() => set("language", l.code)}
                      className="px-3 py-3 rounded-lg text-sm font-medium border transition-all text-center"
                      aria-pressed={data.language === l.code}
                      style={{
                        borderColor: data.language === l.code ? "var(--accent)" : "var(--border)",
                        background: data.language === l.code ? "var(--accent-subtle)" : "transparent",
                        color: "var(--text)"
                      }}>
                      {l.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Step 1: Location */}
          {step === 1 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">Where are you from?</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>Helps us with local context — schemes, weather, mandi prices</p>
              <div className="mb-5">
                <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>State / UT</label>
                <select value={data.state} onChange={e => set("state", e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm border outline-none focus:ring-2"
                  style={{ background: "var(--surface-sunken)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }}>
                  <option value="">Select state</option>
                  {STATES_UTS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>District (optional)</label>
                <input value={data.district} onChange={e => set("district", e.target.value)}
                  className="w-full px-4 py-3 rounded-lg text-sm border outline-none focus:ring-2" placeholder="e.g. Pune, Coimbatore"
                  style={{ background: "var(--surface-sunken)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }} />
              </div>
            </div>
          )}

          {/* Step 2: Age group */}
          {step === 2 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">Your age group</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>Only used to suggest a comfortable default look.</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {AGE_GROUPS.map(ag => (
                  <button key={ag} onClick={() => set("ageBand", ag)}
                    className="px-4 py-4 rounded-xl text-base font-medium border transition-all"
                    aria-pressed={data.ageBand === ag}
                    style={{
                      borderColor: data.ageBand === ag ? "var(--accent)" : "var(--border)",
                      background: data.ageBand === ag ? "var(--accent-subtle)" : "transparent",
                      color: "var(--text)"
                    }}>
                    {ag}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 3: About you */}
          {step === 3 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">A bit more about you</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>This makes answers personal to YOU — your role shapes the examples, depth, and tone.</p>
              <div className="mb-6">
                <label className="block text-sm font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>What do you do? <span style={{ color: "var(--text-muted)" }}>(your role / field / level)</span></label>
                <input value={data.occupation} onChange={e => set("occupation", e.target.value)}
                  placeholder='e.g. "Class 10 student", "AI/ML student", "Software Engineer, 5 yrs", "farmer", "founder"'
                  className="w-full px-4 py-3 rounded-lg text-sm border outline-none focus:ring-2 mb-2"
                  style={{ background: "var(--surface-sunken)", borderColor: "var(--border)", color: "var(--text)", "--tw-ring-color": "var(--accent)" }} />
                <div className="flex flex-wrap gap-1.5">
                  {ROLE_CHIPS.map(r => (
                    <button key={r} onClick={() => set("occupation", r)}
                      className="px-2.5 py-1 rounded-full text-xs border transition-all"
                      style={{
                        borderColor: data.occupation === r ? "var(--accent)" : "var(--border)",
                        background: data.occupation === r ? "var(--accent-subtle)" : "transparent",
                        color: "var(--text-secondary)"
                      }}>{r}</button>
                  ))}
                </div>
              </div>
              <div className="mb-6">
                <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>Gender</label>
                <div className="grid grid-cols-2 gap-2">
                  {GENDERS.map(g => (
                    <button key={g} onClick={() => set("gender", g)}
                      className="px-3 py-3 rounded-lg text-sm font-medium border transition-all"
                      aria-pressed={data.gender === g}
                      style={{
                        borderColor: data.gender === g ? "var(--accent)" : "var(--border)",
                        background: data.gender === g ? "var(--accent-subtle)" : "transparent",
                        color: "var(--text)"
                      }}>
                      {g}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: "var(--text-secondary)" }}>Answer style</label>
                <div className="space-y-2">
                  {ANSWER_STYLES.map(s => (
                    <button key={s.value} onClick={() => set("answerStyle", s.value)}
                      className="w-full text-left px-4 py-3 rounded-lg text-sm border transition-all flex items-center gap-3"
                      aria-pressed={data.answerStyle === s.value}
                      style={{
                        borderColor: data.answerStyle === s.value ? "var(--accent)" : "var(--border)",
                        background: data.answerStyle === s.value ? "var(--accent-subtle)" : "transparent",
                        color: "var(--text)"
                      }}>
                      <span className="font-medium">{s.label}</span>
                      <span style={{ color: "var(--text-muted)" }}>— {s.desc}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Step 4: Interests / what you want help with */}
          {step === 4 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">What can I help you with?</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>Pick what matters to you — I'll tailor answers and suggestions to these. (Change anytime.)</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {INTEREST_OPTIONS.map(opt => {
                  const sel = data.interests.includes(opt);
                  return (
                    <button key={opt}
                      onClick={() => set("interests", sel ? data.interests.filter(x => x !== opt) : [...data.interests, opt])}
                      className="px-3 py-3 rounded-lg text-sm font-medium border transition-all flex items-center gap-2 text-left"
                      aria-pressed={sel}
                      style={{
                        borderColor: sel ? "var(--accent)" : "var(--border)",
                        background: sel ? "var(--accent-subtle)" : "transparent",
                        color: "var(--text)"
                      }}>
                      {sel && <Check size={14} className="flex-shrink-0" style={{ color: "var(--accent)" }} />}
                      {opt}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Step 5: Languages you know */}
          {step === 5 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">Languages you know</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>Powers "explain in…" options and voice locales</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {LANGUAGES.map(l => {
                  const sel = data.languagesKnown.includes(l.code);
                  return (
                    <button key={l.code}
                      onClick={() => set("languagesKnown", sel ? data.languagesKnown.filter(c => c !== l.code) : [...data.languagesKnown, l.code])}
                      className="px-3 py-3 rounded-lg text-sm font-medium border transition-all flex items-center gap-2"
                      aria-pressed={sel}
                      style={{
                        borderColor: sel ? "var(--accent)" : "var(--border)",
                        background: sel ? "var(--accent-subtle)" : "transparent",
                        color: "var(--text)"
                      }}>
                      {sel && <Check size={14} style={{ color: "var(--accent)" }} />}
                      {l.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Step 6: Choose your look */}
          {step === 6 && (
            <div>
              <h2 className="text-xl font-heading font-bold mb-1">Choose your look</h2>
              <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>Suggested for you — change anytime in Settings</p>

              <div className="space-y-3 mb-6">
                {suggestedPresets.map((p, i) => {
                  const pal = palettes[p.defaultPalette];
                  return (
                    <button key={p.id} onClick={() => { set("uiPreset", p.id); set("theme", p.defaultPalette); }}
                      className="w-full text-left p-4 rounded-xl border transition-all flex items-center gap-4"
                      style={{
                        borderColor: data.uiPreset === p.id ? "var(--accent)" : "var(--border)",
                        background: data.uiPreset === p.id ? "var(--accent-subtle)" : "var(--surface-sunken)"
                      }}>
                      <div className="flex gap-1">
                        {(pal?.swatch || p.swatch).map((c, j) => (
                          <div key={j} className="w-5 h-5 rounded-full border" style={{ background: c, borderColor: "var(--border)" }} />
                        ))}
                      </div>
                      <div className="flex-1">
                        <div className="font-medium text-sm flex items-center gap-2">
                          {p.name} <span className="text-xs font-normal" style={{ color: "var(--text-muted)" }}>— {p.subtitle}</span>
                          {i === 0 && <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>Suggested</span>}
                        </div>
                        <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{p.description}</p>
                      </div>
                      {data.uiPreset === p.id && <Check size={16} style={{ color: "var(--accent)" }} />}
                    </button>
                  );
                })}
              </div>

              <button onClick={() => setShowAllLooks(!showAllLooks)} className="text-sm font-medium mb-4 hover:underline" style={{ color: "var(--accent)" }}>
                {showAllLooks ? "Hide all looks" : "See all looks"}
              </button>

              {showAllLooks && (
                <div className="space-y-6 mt-4 pt-4 border-t" style={{ borderColor: "var(--border)" }}>
                  <div>
                    <h4 className="text-xs font-medium mb-2 uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>All presets</h4>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {Object.values(presets).map(p => (
                        <button key={p.id} onClick={() => { set("uiPreset", p.id); set("theme", p.defaultPalette); }}
                          className="p-3 rounded-lg border text-left text-xs transition-all"
                          style={{
                            borderColor: data.uiPreset === p.id ? "var(--accent)" : "var(--border)",
                            background: data.uiPreset === p.id ? "var(--accent-subtle)" : "transparent"
                          }}>
                          <span className="font-medium">{p.name}</span>
                          <span className="block mt-0.5" style={{ color: "var(--text-muted)" }}>{p.subtitle}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <h4 className="text-xs font-medium mb-2 uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Color palette</h4>
                    <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                      {Object.values(palettes).map(p => (
                        <button key={p.id} onClick={() => set("theme", p.id)}
                          className="p-2 rounded-lg border text-xs transition-all flex flex-col items-center gap-1.5"
                          style={{ borderColor: data.theme === p.id ? "var(--accent)" : "var(--border)" }}>
                          <div className="flex gap-0.5">
                            {p.swatch.map((c, i) => <div key={i} className="w-4 h-4 rounded-full" style={{ background: c }} />)}
                          </div>
                          <span>{p.name}</span>
                          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{p.mode}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <h4 className="text-xs font-medium mb-2 uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Cultural motif</h4>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {Object.values(motifs).map(m => (
                        <button key={m.id} onClick={() => set("motif", m.id)}
                          className="p-2 rounded-lg border text-xs text-center transition-all"
                          style={{
                            borderColor: data.motif === m.id ? "var(--accent)" : "var(--border)",
                            background: data.motif === m.id ? "var(--accent-subtle)" : "transparent"
                          }}>
                          {m.name}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-3">
                    <h4 className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Accessibility</h4>
                    <div className="flex items-center gap-3">
                      <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Text size</span>
                      {["S", "M", "L", "XL"].map(s => (
                        <button key={s} onClick={() => set("textScale", s)}
                          className="px-3 py-1.5 rounded text-xs border font-medium"
                          style={{
                            borderColor: data.textScale === s ? "var(--accent)" : "var(--border)",
                            background: data.textScale === s ? "var(--accent-subtle)" : "transparent"
                          }}>{s}</button>
                      ))}
                    </div>
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input type="checkbox" checked={data.highContrast} onChange={e => set("highContrast", e.target.checked)} className="rounded" />
                      <span className="text-sm">High contrast</span>
                    </label>
                    <label className="flex items-center gap-3 cursor-pointer">
                      <Mic size={16} style={{ color: "var(--text-muted)" }} />
                      <input type="checkbox" checked={data.voiceEnabled} onChange={e => set("voiceEnabled", e.target.checked)} className="rounded" />
                      <span className="text-sm">Voice (speak & listen)</span>
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>Off by default</span>
                    </label>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center justify-between mt-8 pt-4 border-t" style={{ borderColor: "var(--border-subtle)" }}>
            <button onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}
              className="flex items-center gap-1 text-sm font-medium disabled:opacity-30 transition-opacity"
              style={{ color: "var(--text-secondary)" }}>
              <ChevronLeft size={16} /> Back
            </button>
            <div className="flex items-center gap-3">
              {/* Quick exit: after the name, the user can finish anytime — the rest is optional
                  and can be completed later or learned from conversation. */}
              {step > 0 && step < STEPS.length - 1 && (
                <button onClick={finish} disabled={saving || !data.name}
                  className="text-xs font-medium hover:underline disabled:opacity-40"
                  style={{ color: "var(--text-muted)" }}>
                  {saving ? "Saving…" : "Skip for now"}
                </button>
              )}
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>{step + 1} of {STEPS.length}</span>
            </div>
            {step < STEPS.length - 1 ? (
              <button onClick={() => setStep(step + 1)} disabled={!canNext()}
                className="flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 transition-all"
                style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                Next <ChevronRight size={16} />
              </button>
            ) : (
              <button onClick={finish} disabled={saving}
                className="flex items-center gap-1 px-6 py-2 rounded-lg text-sm font-medium disabled:opacity-50 transition-all"
                style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                {saving ? "Saving…" : "Finish"} <Check size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}