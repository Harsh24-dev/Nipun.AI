// The 5 UI presets — density, typography, motion, defaults
export const presets = {
  sugam: {
    id: "sugam",
    name: "Sugam",
    subtitle: "Simple & Clear",
    description: "Large text, high contrast, generous spacing, voice featured. For anyone wanting an easy screen.",
    defaultPalette: "sugam",
    textScale: "L",
    radius: "0.75rem",
    motion: "reduced",
    density: "spacious",
    voiceSuggested: true,
    swatch: ["#FFF9F0", "#B45309", "#1A1A1A"],
  },
  sampann: {
    id: "sampann",
    name: "Sampann",
    subtitle: "Balanced",
    description: "Medium text, classic workspace, subtle motion. The comfortable default.",
    defaultPalette: "saffron",
    textScale: "M",
    radius: "0.5rem",
    motion: "subtle",
    density: "normal",
    voiceSuggested: false,
    swatch: ["#0B0E14", "#F97316", "#F5F5F7"],
  },
  nova: {
    id: "nova",
    name: "Nova",
    subtitle: "Modern / Pro",
    description: "Small text, dense info-rich layout, minimal motion, typing-first. For power users.",
    defaultPalette: "indigo",
    textScale: "S",
    radius: "0.375rem",
    motion: "minimal",
    density: "compact",
    voiceSuggested: false,
    swatch: ["#0B1020", "#6366F1", "#EEF0FA"],
  },
  yuva: {
    id: "yuva",
    name: "Yuva",
    subtitle: "Vibrant",
    description: "Bold colors, rounder corners, playful micro-animations. For younger, expressive users.",
    defaultPalette: "yuva",
    textScale: "M",
    radius: "1rem",
    motion: "full",
    density: "normal",
    voiceSuggested: false,
    swatch: ["#150A22", "#D946EF", "#F7ECFF"],
  },
  shaant: {
    id: "shaant",
    name: "Shaant",
    subtitle: "Calm / Reading",
    description: "Warm low-contrast, wide spacing, reduced motion. Perfect for long reading.",
    defaultPalette: "shaant",
    textScale: "M",
    radius: "0.5rem",
    motion: "reduced",
    density: "spacious",
    voiceSuggested: false,
    swatch: ["#F5EFE4", "#B27A3F", "#2B2016"],
  },
};

export const TEXT_SCALES = {
  S: "14px",
  M: "16px",
  L: "18px",
  XL: "20px",
};

// Age → preset shortlist (ordered, first = top suggestion)
export const AGE_PRESET_MAP = {
  "13-17": ["yuva", "nova", "sampann"],
  "18-29": ["nova", "sampann", "yuva"],
  "30-45": ["sampann", "nova", "shaant"],
  "46-60": ["sampann", "sugam", "shaant"],
  "60+": ["sugam", "shaant", "sampann"],
};

// Gender → accent family / motif nudges (just preferences, not gates)
export const GENDER_MOTIF_NUDGE = {
  Female: { accents: ["rose", "teal", "violet", "indigo"], motifs: ["rangoli", "paisley", "blockprint"] },
  Male: { accents: ["saffron", "indigo", "emerald", "obsidian"], motifs: ["blockprint", "jaali", "temple"] },
  "Non-binary": null, // full spread
  "Prefer not to say": null,
};

// Gender → palette nudges
export const GENDER_PALETTE_NUDGE = {
  Female: ["taj", "obsidian", "sky", "mint"],
  Male: ["saffron", "indigo", "emerald", "obsidian"],
  "Non-binary": null,
  "Prefer not to say": null,
};

export function applyPreset(presetId) {
  const p = presets[presetId];
  if (!p) return;
  const root = document.documentElement;
  root.setAttribute("data-preset", presetId);
  root.setAttribute("data-motion", p.motion);
  root.setAttribute("data-density", p.density);
  root.style.setProperty("--radius", p.radius);
}

export function applyTextScale(scale) {
  document.documentElement.style.fontSize = TEXT_SCALES[scale] || TEXT_SCALES.M;
}