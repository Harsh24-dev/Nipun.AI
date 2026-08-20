import React from "react";

export default function NipunLogo({ size = "md", showTagline = false, className = "" }) {
  const sizes = {
    sm: "text-xl",
    md: "text-3xl",
    lg: "text-5xl",
    xl: "text-7xl",
  };

  return (
    <div className={`flex flex-col items-center ${className}`}>
      <span className={`font-display font-bold tracking-tight ${sizes[size]}`} style={{ color: "var(--text)" }}>
        nipun<span style={{ color: "var(--accent)" }}>.ai</span>
      </span>
      {showTagline && (
        <span className="text-xs font-mono tracking-widest uppercase mt-1" style={{ color: "var(--text-muted)" }}>
          Sovereign Multi-Agent OS
        </span>
      )}
    </div>
  );
}