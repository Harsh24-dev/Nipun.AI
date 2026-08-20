import React, { useState, useEffect } from "react";
import NipunLogo from "@/components/nipun/NipunLogo";

const VALUE_PROPS = [
  { lang: "हिन्दी", text: "अपनी भाषा में सरकारी योजनाएं खोजें" },
  { lang: "English", text: "Grounded answers with real sources" },
  { lang: "தமிழ்", text: "உங்கள் மொழியில் AI உதவியாளர்" },
  { lang: "తెలుగు", text: "మీ భాషలో AI సహాయకుడు" },
  { lang: "ਪੰਜਾਬੀ", text: "ਆਪਣੀ ਭਾਸ਼ਾ ਵਿੱਚ AI ਸਹਾਇਕ" },
  { lang: "ગુજરાતી", text: "તમારી ભાષામાં AI સહાયક" },
  { lang: "मराठी", text: "तुमच्या भाषेत AI सहाय्यक" },
];

export default function AuthShell({ children, title }) {
  const [propIdx, setPropIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setPropIdx(i => (i + 1) % VALUE_PROPS.length), 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="min-h-screen flex" style={{ background: "var(--background)" }}>
      {/* Left brand panel */}
      <div className="hidden lg:flex flex-col justify-center items-center w-2/5 relative p-12 motif-bg" style={{ background: "var(--surface-sunken)" }}>
        <NipunLogo size="lg" showTagline />
        <div className="mt-12 h-20 flex items-center">
          <div className="text-center transition-all duration-500" key={propIdx}>
            <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
              {VALUE_PROPS[propIdx].lang}
            </span>
            <p className="mt-2 text-lg" style={{ color: "var(--text-secondary)" }}>
              {VALUE_PROPS[propIdx].text}
            </p>
          </div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          <div className="lg:hidden mb-8 text-center">
            <NipunLogo size="md" showTagline />
          </div>
          {title && (
            <h1 className="text-2xl font-heading font-bold mb-6" style={{ color: "var(--text)" }}>{title}</h1>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}