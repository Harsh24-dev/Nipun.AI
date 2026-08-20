// Indian states/UTs → region mapping, plus region → default palette

export const STATES_UTS = [
  // States
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
  "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
  "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
  "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
  "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
  "Uttar Pradesh", "Uttarakhand", "West Bengal",
  // UTs
  "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
  "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
];

export const STATE_REGION_MAP = {
  "Andhra Pradesh": "south", "Arunachal Pradesh": "north-east", "Assam": "north-east",
  "Bihar": "east", "Chhattisgarh": "central", "Goa": "west", "Gujarat": "west",
  "Haryana": "north", "Himachal Pradesh": "north", "Jharkhand": "east",
  "Karnataka": "south", "Kerala": "south", "Madhya Pradesh": "central",
  "Maharashtra": "west", "Manipur": "north-east", "Meghalaya": "north-east",
  "Mizoram": "north-east", "Nagaland": "north-east", "Odisha": "east",
  "Punjab": "north", "Rajasthan": "north", "Sikkim": "north-east",
  "Tamil Nadu": "south", "Telangana": "south", "Tripura": "north-east",
  "Uttar Pradesh": "north", "Uttarakhand": "north", "West Bengal": "east",
  "Andaman and Nicobar Islands": "south", "Chandigarh": "north",
  "Dadra and Nagar Haveli and Daman and Diu": "west",
  "Delhi": "north", "Jammu and Kashmir": "north", "Ladakh": "north",
  "Lakshadweep": "south", "Puducherry": "south",
};

// Region → default palette
export const REGION_PALETTE_MAP = {
  north: "saffron",
  south: "taj",
  "north-east": "mint",
  west: "sugam",
  east: "indigo",
  central: "taj",
};

// Region → light alternative palette
export const REGION_LIGHT_ALT = {
  north: "taj",
  south: "taj",
  "north-east": "mint",
  west: "sugam",
  east: "sky",
  central: "taj",
};

export function getRegionForState(state) {
  return STATE_REGION_MAP[state] || "north";
}