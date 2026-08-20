import React, { useState } from "react";
import { Copy, Check } from "lucide-react";

export default function CodeEditorCard({ card }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(card.code || "");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div>
      {card.title && <h3 className="font-semibold text-sm mb-2">{card.title}</h3>}
      <div className="relative rounded-lg overflow-hidden" style={{ background: "#1e1e1e" }}>
        <div className="flex items-center justify-between px-3 py-1.5 text-[10px]" style={{ background: "#2d2d2d", color: "#858585" }}>
          <span>{card.codeLanguage || "code"}</span>
          <button onClick={handleCopy} className="flex items-center gap-1 hover:opacity-80">
            {copied ? <Check size={10} /> : <Copy size={10} />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="p-4 text-xs overflow-x-auto" style={{ color: "#d4d4d4" }}>
          <code>{card.code || ""}</code>
        </pre>
      </div>
    </div>
  );
}