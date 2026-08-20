// DEAD MODULE — intentionally left empty.
//
// Card resolution now lives in a single place: the CARD_MAP object and resolveCard()
// helper in `@/components/workspace/ResponseCardRenderer.jsx`. This registry was never
// imported anywhere and its normalization logic had diverged from the live one, so it
// was a maintenance trap. Add or change card types in ResponseCardRenderer.jsx instead.

export {};
