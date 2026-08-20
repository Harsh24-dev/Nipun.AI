import React, { useState } from "react";
import { HelpCircle } from "lucide-react";

export default function ClarifyCard({ card, onSubmitClarification }) {
  const form = card.form;
  const [values, setValues] = useState({});

  if (!form) return null;

  const handleSubmit = () => {
    if (onSubmitClarification) onSubmitClarification(values);
  };

  const handleSkip = () => {
    if (onSubmitClarification) onSubmitClarification({});
  };

  return (
    <div>
      {card.title && <h3 className="font-semibold text-sm mb-2">{card.title}</h3>}
      {card.summary && <p className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>{card.summary}</p>}
      <div className="space-y-3">
        {(form.fields || []).map(f => (
          <div key={f.name}>
            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
              {f.label} {f.required && <span style={{ color: "var(--destructive)" }}>*</span>}
            </label>
            {f.type === "select" ? (
              <select value={values[f.name] || ""} onChange={e => setValues(prev => ({ ...prev, [f.name]: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg text-sm border outline-none"
                style={{ background: "var(--surface-sunken)", borderColor: "var(--border)", color: "var(--text)" }}>
                <option value="">{f.placeholder || "Select…"}</option>
                {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : f.type === "multiselect" ? (
              <div className="flex flex-wrap gap-1.5">
                {(f.options || []).map(o => {
                  const sel = (values[f.name] || []).includes(o);
                  return (
                    <button key={o} onClick={() => {
                      const curr = values[f.name] || [];
                      setValues(prev => ({ ...prev, [f.name]: sel ? curr.filter(x => x !== o) : [...curr, o] }));
                    }} className="px-2 py-1 rounded text-xs border" style={{
                      borderColor: sel ? "var(--accent)" : "var(--border)",
                      background: sel ? "var(--accent-subtle)" : "transparent"
                    }}>{o}</button>
                  );
                })}
              </div>
            ) : (
              <input type={f.type === "number" ? "number" : "text"} value={values[f.name] || ""}
                onChange={e => setValues(prev => ({ ...prev, [f.name]: e.target.value }))}
                placeholder={f.placeholder || ""}
                className="w-full px-3 py-2 rounded-lg text-sm border outline-none"
                style={{ background: "var(--surface-sunken)", borderColor: "var(--border)", color: "var(--text)" }} />
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-2 mt-4">
        <button onClick={handleSubmit} className="px-4 py-2 rounded-lg text-sm font-medium"
          style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
          {form.submitLabel || "Submit"}
        </button>
        {form.allowSkip && (
          <button onClick={handleSkip} className="px-4 py-2 rounded-lg text-sm border"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
            {form.skipLabel || "Skip"}
          </button>
        )}
      </div>
    </div>
  );
}