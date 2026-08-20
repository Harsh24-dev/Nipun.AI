from prometheus_client import Counter, Gauge, Histogram

from src.core.logging import get_logger

log = get_logger("core.metrics")

# ── Latency buckets (ms) ──────────────────────────────────────────────────────
_LATENCY_BUCKETS = (25, 50, 100, 200, 500, 1000, 2000, 5000, 10000)

# ── Request metrics ───────────────────────────────────────────────────────────
QUERIES_TOTAL = Counter(
    "nipun_queries_total",
    "Total queries received",
    ["domain", "language", "status", "agent"],
)

REQUEST_DURATION = Histogram(
    "nipun_request_duration_ms",
    "End-to-end request duration in milliseconds",
    ["endpoint", "status_code"],
    buckets=_LATENCY_BUCKETS,
)

WS_CONNECTIONS = Gauge(
    "nipun_ws_connections",
    "Active WebSocket connections",
)

# ── Cache metrics ─────────────────────────────────────────────────────────────
CACHE_HITS = Counter(
    "nipun_cache_hits_total",
    "Cache hits",
    ["service", "cache_type"],
)

CACHE_MISSES = Counter(
    "nipun_cache_misses_total",
    "Cache misses",
    ["service", "cache_type"],
)

# ── LLM metrics ───────────────────────────────────────────────────────────────
LLM_TOKENS = Counter(
    "nipun_llm_tokens_total",
    "LLM tokens consumed",
    ["model", "provider", "direction"],  # direction: input | output
)

LLM_DURATION = Histogram(
    "nipun_llm_duration_ms",
    "LLM call duration in milliseconds",
    ["model", "provider"],
    buckets=_LATENCY_BUCKETS,
)

LLM_ERRORS = Counter(
    "nipun_llm_errors_total",
    "LLM call errors",
    ["model", "provider", "error_type"],
)

# ── Retrieval metrics ─────────────────────────────────────────────────────────
RETRIEVAL_DURATION = Histogram(
    "nipun_retrieval_duration_ms",
    "Retrieval pipeline duration in milliseconds",
    ["stage"],  # dense | sparse | rrf | rerank | total
    buckets=_LATENCY_BUCKETS,
)

RETRIEVAL_TOTAL = Counter(
    "nipun_retrieval_total",
    "Total retrieval requests",
    ["domain", "language", "method"],
)

# ── Memory metrics ────────────────────────────────────────────────────────────
MEMORY_ASSEMBLY_DURATION = Histogram(
    "nipun_memory_assembly_ms",
    "Memory context assembly duration",
    buckets=(5, 10, 20, 35, 50, 100, 200),
)

# ── Ingestion metrics ─────────────────────────────────────────────────────────
DOCUMENTS_INDEXED = Counter(
    "nipun_documents_indexed_total",
    "Documents indexed",
    ["domain", "language"],
)

INGESTION_DURATION = Histogram(
    "nipun_ingestion_duration_ms",
    "Document ingestion duration",
    ["domain", "stage"],
    buckets=(100, 500, 1000, 5000, 30000, 120000),
)

# ── Agent metrics ─────────────────────────────────────────────────────────────
AGENT_CALLS = Counter(
    "nipun_agent_calls_total",
    "Agent invocations",
    ["agent", "domain", "status"],
)

AGENT_DURATION = Histogram(
    "nipun_agent_duration_ms",
    "Agent execution duration",
    ["agent", "domain"],
    buckets=_LATENCY_BUCKETS,
)

# ── Error metrics ─────────────────────────────────────────────────────────────
ERRORS_TOTAL = Counter(
    "nipun_errors_total",
    "Application errors",
    ["service", "error_code"],
)

# ── Safety & verification metrics ─────────────────────────────────────────────
SAFETY_PRESCREEN_TOTAL = Counter(
    "nipun_safety_prescreen_total",
    "Intake safety pre-screen classifications",
    ["tag", "method"],  # tag: normal|self_harm|medical_emergency|child_safety|fraud_scam|harmful_instructions ; method: rules|llm
)

SAFETY_GATE_TOTAL = Counter(
    "nipun_safety_gate_total",
    "Verification/safety gate outcomes",
    ["outcome"],  # answered | abstained | safe_redirect | disclaimer_attached
)

ABSTENTIONS_TOTAL = Counter(
    "nipun_abstentions_total",
    "Responses that abstained due to low confidence",
    ["domain"],
)

RELIABILITY_SCORE = Histogram(
    "nipun_reliability_score",
    "Calibrated multi-signal reliability score attached to delivered answers",
    buckets=(0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.85, 1.0),
)

RELIABILITY_BAND_TOTAL = Counter(
    "nipun_reliability_band_total",
    "Delivered answers by reliability band",
    ["band"],  # high | medium | low | very_low | not_applicable
)

# ── Agentic RAG loop metrics ──────────────────────────────────────────────────
RAG_LOOPS_PER_QUERY = Histogram(
    "nipun_rag_loops_per_query",
    "Number of retrieve/rewrite loops taken per query",
    buckets=(0, 1, 2, 3, 4, 5),
)

CLAIMS_UNSUPPORTED_RATIO = Histogram(
    "nipun_claims_unsupported_ratio",
    "Fraction of a draft's atomic claims that were unsupported by evidence",
    buckets=(0.0, 0.1, 0.25, 0.5, 0.75, 1.0),
)

VERIFICATION_LATENCY = Histogram(
    "nipun_verification_latency_ms",
    "Claim-verification latency in milliseconds",
    buckets=_LATENCY_BUCKETS,
)

DOCUMENTS_GRADED = Counter(
    "nipun_documents_graded_total",
    "Chunks graded for relevance",
    ["verdict"],  # relevant | irrelevant
)

# ── Planner metrics ───────────────────────────────────────────────────────────
PLAN_ROUTE_TOTAL = Counter(
    "nipun_plan_route_total",
    "Route classifications at orchestrator start",
    ["route", "method"],  # route: simple_answer|agentic_rag|multi_hop|research|task_execution
)

PLANS_GENERATED = Histogram(
    "nipun_plans_generated",
    "Number of candidate plans generated per non-trivial query",
    buckets=(1, 2, 3),
)

SUBQUESTIONS_PER_QUERY = Histogram(
    "nipun_subquestions_per_query",
    "Sub-questions produced by multi-hop decomposition",
    buckets=(1, 2, 3, 4, 5),
)

# ── Adaptive-explanation metrics ──────────────────────────────────────────────
EXPLANATION_MODALITY_TOTAL = Counter(
    "nipun_explanation_modality_total",
    "Chosen explanation modality",
    ["modality"],  # prose | step_cards | comparison_table | timeline | diagram | map | interactive_widget
)

EXPLANATION_DEPTH_TOTAL = Counter(
    "nipun_explanation_depth_total",
    "Chosen explanation depth",
    ["depth"],  # quick | working | mastery
)

EXPLAIN_DIFFERENTLY_CLICKS = Counter(
    "nipun_explain_differently_clicks_total",
    "explain_differently affordance clicks",
    ["mode"],  # simpler | deeper | with_example | in_language
)

# ── MCP tools + execution metrics ─────────────────────────────────────────────
TOOL_CALLS_TOTAL = Counter(
    "nipun_tool_calls_total",
    "MCP tool invocations",
    ["tool", "status"],  # status: ok | unavailable | error | blocked
)

TASK_LIFECYCLE_TOTAL = Counter(
    "nipun_task_lifecycle_total",
    "PREPARE→CONFIRM→EXECUTE→AUDIT lifecycle transitions",
    ["phase", "task"],  # phase: prepare | confirm | execute | reject | audit
)

CIRCUIT_BREAKER_TRIPS = Counter(
    "nipun_circuit_breaker_trips_total",
    "Per-session circuit-breaker trips",
    ["kind"],  # tool | agent
)

CREDENTIAL_BLOCKS_TOTAL = Counter(
    "nipun_credential_blocks_total",
    "Payloads blocked for containing raw credentials",
    ["type"],
)

A2A_CARD_VERIFICATIONS = Counter(
    "nipun_a2a_card_verifications_total",
    "A2A Agent Card verification outcomes",
    ["outcome"],  # verified | bad_signature | untrusted | malformed
)

# ── Evaluation gauges — updated by `make eval` ────────────────────────────────
EVAL_PRECISION_AT_K = Gauge(
    "nipun_eval_precision_at_k",
    "Retrieval precision@k on the domain golden set",
    ["domain"],
)

EVAL_NDCG_AT_10 = Gauge(
    "nipun_eval_ndcg_at_10",
    "Retrieval nDCG@10 on the domain golden set",
    ["domain"],
)

EVAL_FAITHFULNESS = Gauge(
    "nipun_eval_faithfulness",
    "Answer faithfulness (grounded-in-sources) on the domain golden set",
    ["domain"],
)

EVAL_ABSTENTION_CORRECTNESS = Gauge(
    "nipun_eval_abstention_correctness",
    "Fraction of should-abstain / should-answer decisions made correctly",
    ["domain"],
)

EVAL_CITATION_VALIDITY = Gauge(
    "nipun_eval_citation_validity",
    "Fraction of expected citations present and well-formed",
    ["domain"],
)

# ── System metrics ────────────────────────────────────────────────────────────
ACTIVE_SESSIONS = Gauge(
    "nipun_active_sessions",
    "Active user sessions",
)

QUEUE_DEPTH = Gauge(
    "nipun_queue_depth",
    "Celery task queue depth",
    ["queue_name"],
)

log.debug("prometheus_metrics_registered")
