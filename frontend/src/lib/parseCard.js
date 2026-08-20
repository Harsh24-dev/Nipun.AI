// Defensively parse a response_card from the backend
// Accepts both snake_case and camelCase keys

function get(obj, ...keys) {
  for (const k of keys) {
    if (obj[k] !== undefined) return obj[k];
  }
  return undefined;
}

export function parseResponseCard(raw) {
  if (!raw || typeof raw !== "object") {
    return { cardType: "error", summary: "Failed to parse response", language: "en" };
  }

  return {
    cardType: get(raw, "cardType", "card_type", "type") || "answer",
    language: get(raw, "language") || "en",
    title: get(raw, "title") || "",
    summary: get(raw, "summary") || "",
    sources: get(raw, "sources") || [],
    speechText: get(raw, "speech_text", "speechText") || "",
    correlationId: get(raw, "correlation_id", "correlationId") || "",
    disclaimer: get(raw, "disclaimer") || null,
    confidence: get(raw, "confidence") ?? null,
    abstained: get(raw, "abstained") || false,
    // DELIVER-WITH-SCORE — calibrated reliability verdict from the backend.
    reliability: get(raw, "reliability") || null,
    lowConfidence: get(raw, "low_confidence", "lowConfidence") || false,
    keyTakeaway: get(raw, "key_takeaway", "keyTakeaway") || null,
    // Type-specific
    steps: get(raw, "steps") || [],
    planCols: get(raw, "plan_cols", "planCols") || [],
    planRows: get(raw, "plan_rows", "planRows") || [],
    plan: get(raw, "plan") || null,
    prices: get(raw, "prices") || [],
    weather: get(raw, "weather") || null,
    schemes: get(raw, "schemes") || [],
    form: get(raw, "form") || null,
    options: get(raw, "options") || [],
    code: get(raw, "code") || "",
    codeLanguage: get(raw, "code_language", "codeLanguage") || "text",
    mindmapNodes: get(raw, "mindmap_nodes", "mindmapNodes") || [],
    timeline: get(raw, "timeline") || [],
    comparisonTable: get(raw, "comparison_table", "comparisonTable") || null,
    diagram: get(raw, "diagram") || null,
    mapData: get(raw, "map_data", "mapData") || null,
    widget: get(raw, "widget") || null,
    url: get(raw, "url") || null,
    book: get(raw, "book") || null,
    explainDifferently: get(raw, "explain_differently", "explainDifferently") || [],
    // Suggested next questions the user can tap to ask — sent by the backend as `followups`.
    followups: get(raw, "followups", "follow_ups", "followUps") || [],
    understandingCheck: get(raw, "understanding_check", "understandingCheck") || null,
    // Study resources — videos / images / article links to see & explore a topic.
    resources: get(raw, "resources") || null,
    // IPA agent task — the goal the browser agent will execute (cardType "agent_task").
    goal: get(raw, "goal") || null,
    // Task execution — the concrete work an assistant prepared (job apply, form fill, ITR…):
    // the filled field values, the portal link, what's still needed, and the confirm action.
    filledForm: get(raw, "filled_form", "filledForm") || null,
    portal: get(raw, "portal") || null,
    missingFields: get(raw, "missing_fields", "missingFields") || null,
    readyForHandoff: get(raw, "ready_for_handoff", "readyForHandoff") ?? null,
    confirmation: get(raw, "confirmation") || null,
    // Generated deliverable (pptx/docx/…) available for download.
    fileUrl: get(raw, "file_url", "fileUrl") || null,
    filename: get(raw, "filename") || null,
    download: get(raw, "download") || null,
    // Inline preview of the file's slides/pages (heading, explanation, bullets, chart, image).
    preview: get(raw, "preview") || null,
    // Rich embeds rendered INLINE in the answer (files, tables, videos…), referenced from the
    // summary by [[embed:id]] markers. Normalise each so the existing card renderers accept it.
    embeds: (get(raw, "embeds") || []).map((e) => ({
      ...e,
      fileUrl: e.file_url || e.fileUrl || null,
      mapData: e.map_data || e.mapData || null,
      comparisonTable: e.comparison_table || e.comparisonTable || null,
    })),
    // Raw for extensibility
    _raw: raw,
  };
}