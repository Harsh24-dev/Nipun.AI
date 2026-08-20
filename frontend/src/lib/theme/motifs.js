// Cultural motif definitions — decorative layer independent of palette
export const motifs = {
  rangoli: {
    id: "rangoli",
    name: "Rangoli",
    description: "Kolam/rangoli geometric flourishes, marigold+teal lean",
    accentFamily: "marigold",
    region: "south",
  },
  paisley: {
    id: "paisley",
    name: "Paisley",
    description: "Ambi/paisley ornament, warm jewel-tone lean",
    accentFamily: "jewel",
    region: "west",
  },
  blockprint: {
    id: "blockprint",
    name: "Block Print",
    description: "Bagru/ajrakh block-print, indigo/rust lean",
    accentFamily: "indigo",
    region: "west",
  },
  jaali: {
    id: "jaali",
    name: "Jaali",
    description: "Mughal lattice screens, calm neutral + gold lean",
    accentFamily: "gold",
    region: "north",
  },
  warli: {
    id: "warli",
    name: "Warli",
    description: "Minimalist tribal line-art, earthy monochrome",
    accentFamily: "earthy",
    region: "central",
  },
  temple: {
    id: "temple",
    name: "Temple",
    description: "South-Indian temple geometry + gold",
    accentFamily: "gold",
    region: "south",
  },
  himalaya: {
    id: "himalaya",
    name: "Himalaya",
    description: "Clean, airy, mountain/pine lean",
    accentFamily: "pine",
    region: "north-east",
  },
  minimal: {
    id: "minimal",
    name: "Minimal",
    description: "No pattern, only Indian accent + language flavor",
    accentFamily: "neutral",
    region: null,
  },
};

// Region → suggested motifs (first = top suggestion)
export const REGION_MOTIF_MAP = {
  north: ["jaali", "rangoli", "blockprint"],
  south: ["temple", "rangoli", "paisley"],
  west: ["blockprint", "paisley", "rangoli"],
  east: ["rangoli", "warli", "jaali"],
  "north-east": ["himalaya", "warli", "minimal"],
  central: ["warli", "rangoli", "blockprint"],
};

export function applyMotif(motifId) {
  document.documentElement.setAttribute("data-motif", motifId || "minimal");
}