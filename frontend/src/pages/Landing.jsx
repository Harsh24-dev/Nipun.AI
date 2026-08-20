import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Globe, Shield, Mic, FileText, TrendingUp, Users, BookOpen, Heart,
  Scale, Sprout, Landmark, GraduationCap, Briefcase, Menu, X, ChevronRight,
  Eye, Accessibility, Sun, MapPin
} from "lucide-react";
import NipunLogo from "@/components/nipun/NipunLogo";
import { LANGUAGES, CODE_SWITCH_BADGES } from "@/lib/i18n";

const MOCK_CHATS = [
  { lang: "हिन्दी", q: "PM-KISAN योजना के लिए कौन पात्र है?", a: "PM-KISAN के तहत, सभी भूमिधारक किसान परिवार ₹6,000/वर्ष प्राप्त कर सकते हैं..." },
  { lang: "English", q: "What's the MSP for wheat this season?", a: "The MSP for wheat in Rabi 2025-26 is ₹2,275 per quintal, a ₹150 increase..." },
  { lang: "தமிழ்", q: "FIR ஆன்லைனில் எப்படி பதிவு செய்வது?", a: "நீங்கள் உங்கள் மாநில போலீஸ் இணையதளத்தில் மின்-FIR பதிவு செய்யலாம்..." },
];

const FEATURES = [
  { icon: Shield, title: "Grounded Answers", desc: "Every response cites real sources. If we can't verify, we tell you — never guesses." },
  { icon: Globe, title: "Multi-Agent Domains", desc: "Legal, farming, government schemes, finance, health, education, jobs, travel & more." },
  { icon: Mic, title: "Voice In & Out", desc: "Speak in your language, hear answers read aloud. Perfect for every age group." },
  { icon: FileText, title: "Ask Your Documents", desc: "Upload any document and ask questions grounded entirely in its content." },
  { icon: TrendingUp, title: "Live Tools", desc: "Mandi prices, weather, web search, finance calculators — real-time data at your fingertips." },
  { icon: Accessibility, title: "Personalized UI", desc: "An interface that adapts to your age, language, and comfort. Large text, voice, or pro-dense." },
];

const USE_CASES = [
  { icon: Sprout, title: "For Farmers", desc: "Check MSP, weather forecasts, soil health cards, PM-KISAN status, and mandi prices — all in your language.", img: "🌾" },
  { icon: Scale, title: "For Citizens", desc: "File an RTI, find eligible government schemes, understand your legal rights, get step-by-step guidance.", img: "⚖️" },
  { icon: GraduationCap, title: "For Students", desc: "NCERT help, exam prep, career guidance, scholarship search — with understanding checks built in.", img: "📚" },
  { icon: Briefcase, title: "For Small Business", desc: "GST filing guidance, MSME schemes, loan EMI calculators, compliance checklists — no jargon.", img: "💼" },
];

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [chatIdx, setChatIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setChatIdx(i => (i + 1) % MOCK_CHATS.length), 4000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="min-h-screen" style={{ background: "var(--background)", color: "var(--text)" }}>
      <nav className="sticky top-0 z-50 backdrop-blur-md border-b" style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--background) 85%, transparent)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between h-16">
          <NipunLogo size="sm" />
          <div className="hidden md:flex items-center gap-8 text-sm" style={{ color: "var(--text-secondary)" }}>
            <a href="#features" className="hover:opacity-80 transition-opacity">Features</a>
            <a href="#languages" className="hover:opacity-80 transition-opacity">Languages</a>
            <a href="#use-cases" className="hover:opacity-80 transition-opacity">For Citizens</a>
            <a href="#trust" className="hover:opacity-80 transition-opacity">Trust</a>
          </div>
          <div className="hidden md:flex items-center gap-3">
            <Link to="/login" className="px-4 py-2 text-sm font-medium rounded-lg transition-colors" style={{ color: "var(--text-secondary)" }}>
              Log in
            </Link>
            <Link to="/signup" className="px-4 py-2 text-sm font-medium rounded-lg transition-colors" style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
              Get started
            </Link>
          </div>
          <button className="md:hidden p-2" onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu">
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        {menuOpen && (
          <div className="md:hidden px-4 pb-4 flex flex-col gap-3 border-t" style={{ borderColor: "var(--border)" }}>
            <a href="#features" className="py-2 text-sm">Features</a>
            <a href="#languages" className="py-2 text-sm">Languages</a>
            <a href="#use-cases" className="py-2 text-sm">For Citizens</a>
            <Link to="/login" className="py-2 text-sm">Log in</Link>
            <Link to="/signup" className="py-2 px-4 text-sm text-center rounded-lg" style={{ background: "var(--accent)", color: "var(--accent-text)" }}>Get started</Link>
          </div>
        )}
      </nav>

      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-20 pb-24 md:pt-32 md:pb-36">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono tracking-wide mb-6" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
                <Shield size={12} /> Sovereign Multi-Agent OS
              </div>
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-heading font-bold leading-tight mb-6" style={{ color: "var(--text)" }}>
                India's AI assistant that speaks{" "}
                <span style={{ color: "var(--accent)" }}>your language</span>
              </h1>
              <p className="text-lg mb-8 leading-relaxed max-w-lg" style={{ color: "var(--text-secondary)" }}>
                Grounded answers across legal, farming, government schemes, education, health & finance — in Hindi, Tamil, Telugu, and 4 more languages. Never guessed, always cited.
              </p>
              <div className="flex flex-wrap gap-3">
                <Link to="/signup" className="inline-flex items-center gap-2 px-6 py-3 text-base font-medium rounded-xl transition-all hover:scale-[1.02]" style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                  Get started free <ChevronRight size={18} />
                </Link>
                <a href="#features" className="inline-flex items-center gap-2 px-6 py-3 text-base font-medium rounded-xl border transition-all" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
                  See how it works
                </a>
              </div>
            </div>
            {/* Mock chat animation */}
            <div className="relative">
              <div className="rounded-2xl p-6 border shadow-lg" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                <div className="flex items-center gap-2 mb-4 pb-3 border-b" style={{ borderColor: "var(--border-subtle)" }}>
                  <div className="w-2 h-2 rounded-full" style={{ background: "var(--success)" }} />
                  <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>nipun.ai</span>
                </div>
                <AnimatePresence mode="wait">
                  <motion.div
                    key={chatIdx}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.4 }}
                  >
                    <div className="mb-3">
                      <span className="inline-block px-2 py-0.5 rounded text-xs font-medium mb-2" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
                        {MOCK_CHATS[chatIdx].lang}
                      </span>
                      <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{MOCK_CHATS[chatIdx].q}</p>
                    </div>
                    <div className="rounded-lg p-4 mt-3" style={{ background: "var(--surface-sunken)" }}>
                      <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{MOCK_CHATS[chatIdx].a}</p>
                      <div className="flex items-center gap-2 mt-3 pt-2 border-t" style={{ borderColor: "var(--border-subtle)" }}>
                        <Shield size={10} style={{ color: "var(--success)" }} />
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>3 sources cited</span>
                      </div>
                    </div>
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Language strip */}
      <section id="languages" className="py-16 border-y" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 text-center">
          <h2 className="text-2xl font-heading font-semibold mb-2">Ask in any language</h2>
          <p className="text-sm mb-8" style={{ color: "var(--text-muted)" }}>7 languages, natural code-switching, native script rendering</p>
          <div className="flex flex-wrap justify-center gap-3 mb-6">
            {LANGUAGES.map(l => (
              <span key={l.code} className="px-4 py-2 rounded-full text-sm font-medium border transition-colors hover:scale-105" style={{ borderColor: "var(--border)", background: "var(--surface-raised)", color: "var(--text)" }}>
                {l.label}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            {CODE_SWITCH_BADGES.map(b => (
              <span key={b} className="px-3 py-1 rounded-full text-xs font-mono" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
                {b}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section id="features" className="py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-heading font-bold mb-3">Built for real needs</h2>
            <p className="max-w-xl mx-auto" style={{ color: "var(--text-secondary)" }}>Not another chatbot. A grounded, multi-domain assistant that cites sources and adapts to you.</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f, i) => (
              <div key={i} className="rounded-xl p-6 border transition-all hover:shadow-md" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                <div className="w-10 h-10 rounded-lg flex items-center justify-center mb-4" style={{ background: "var(--accent-subtle)" }}>
                  <f.icon size={20} style={{ color: "var(--accent)" }} />
                </div>
                <h3 className="text-base font-semibold mb-2">{f.title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="use-cases" className="py-20" style={{ background: "var(--surface-sunken)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <h2 className="text-3xl font-heading font-bold text-center mb-14">Who is it for?</h2>
          <div className="space-y-16">
            {USE_CASES.map((uc, i) => (
              <div key={i} className={`flex flex-col ${i % 2 ? "md:flex-row-reverse" : "md:flex-row"} gap-8 items-center`}>
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "var(--accent-subtle)" }}>
                      <uc.icon size={16} style={{ color: "var(--accent)" }} />
                    </div>
                    <h3 className="text-xl font-semibold">{uc.title}</h3>
                  </div>
                  <p className="leading-relaxed" style={{ color: "var(--text-secondary)" }}>{uc.desc}</p>
                </div>
                <div className="flex-1 flex justify-center">
                  <div className="w-48 h-48 rounded-2xl flex items-center justify-center text-6xl" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
                    {uc.img}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trust / compliance */}
      <section id="trust" className="py-16 border-y" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="max-w-4xl mx-auto px-4 sm:px-6 text-center">
          <Shield size={32} className="mx-auto mb-4" style={{ color: "var(--accent)" }} />
          <h2 className="text-2xl font-heading font-bold mb-4">Built for India. Built on trust.</h2>
          <div className="grid sm:grid-cols-3 gap-6 mt-8">
            <div className="p-4">
              <h4 className="font-semibold text-sm mb-1">DPDPA-2023 Aligned</h4>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>Your data stays protected under India's data privacy law.</p>
            </div>
            <div className="p-4">
              <h4 className="font-semibold text-sm mb-1">Grounded-or-Abstain</h4>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>We cite a source or tell you we can't verify. Never fabricated answers.</p>
            </div>
            <div className="p-4">
              <h4 className="font-semibold text-sm mb-1">Sovereign Sandbox</h4>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>Local processing mode available. Your queries, your control.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Personalization teaser */}
      <section className="py-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 text-center">
          <h2 className="text-3xl font-heading font-bold mb-3">An interface that adapts to you</h2>
          <p className="mb-10 max-w-lg mx-auto" style={{ color: "var(--text-secondary)" }}>
            From large, calm screens for elders to dense, pro layouts for power users — choose your look.
          </p>
          <div className="flex flex-col sm:flex-row gap-6 justify-center">
            <div className="rounded-xl p-6 border flex-1 max-w-xs mx-auto" style={{ background: "#FFF9F0", borderColor: "#D4C4A8", color: "#1A1A1A" }}>
              <h4 className="font-bold text-lg mb-1">Sugam</h4>
              <p className="text-sm opacity-70">Simple & Clear — big text, voice-first</p>
            </div>
            <div className="rounded-xl p-6 border flex-1 max-w-xs mx-auto" style={{ background: "#0B1020", borderColor: "rgba(255,255,255,0.1)", color: "#EEF0FA" }}>
              <h4 className="font-bold text-lg mb-1">Nova</h4>
              <p className="text-sm opacity-70">Modern / Pro — dense, efficient</p>
            </div>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="py-20" style={{ background: "var(--surface-sunken)" }}>
        <div className="max-w-3xl mx-auto px-4 sm:px-6 text-center">
          <h2 className="text-3xl font-heading font-bold mb-4">Start asking, in your language</h2>
          <p className="mb-8" style={{ color: "var(--text-secondary)" }}>Free to use. No credit card needed. Your AI assistant for India.</p>
          <Link to="/signup" className="inline-flex items-center gap-2 px-8 py-4 text-lg font-medium rounded-xl transition-all hover:scale-[1.02]" style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
            Get started free <ChevronRight size={20} />
          </Link>
        </div>
      </section>

      <footer className="py-12 border-t" style={{ borderColor: "var(--border)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex flex-col md:flex-row justify-between items-center gap-6">
            <NipunLogo size="sm" showTagline />
            <div className="flex flex-wrap gap-4 text-xs" style={{ color: "var(--text-muted)" }}>
              {LANGUAGES.map(l => <span key={l.code}>{l.label}</span>)}
            </div>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              © 2026 nipun.ai — DPDPA-2023 compliant
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}