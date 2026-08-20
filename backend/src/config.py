from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        env_ignore_empty=True,
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "Nipun.AI"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_PORT: int = 8000
    DEBUG: bool = False
    SECRET_KEY: str = Field(min_length=32)

    # ── CORS ────────────────────────────────────────────────────────────────
    # Comma-separated list (or JSON list) of allowed browser origins for PRODUCTION.
    # In development any localhost/127.0.0.1/LAN origin is allowed automatically (see
    # main.py), so this only needs to be set for staging/production. Empty in prod → no
    # cross-origin browser access (same-origin behind the reverse proxy still works).
    CORS_ALLOW_ORIGINS: list[str] = []

    # ── Bootstrap admin ───────────────────────────────────────────────────────
    # On first start, if no admin exists, one is created from these. In production you
    # MUST override BOOTSTRAP_ADMIN_EMAIL/PASSWORD via env (the defaults are dev-only and
    # publicly known). Set BOOTSTRAP_ADMIN_ENABLED=false to skip auto-creation entirely.
    BOOTSTRAP_ADMIN_ENABLED: bool = True
    BOOTSTRAP_ADMIN_NAME: str = "Harsh Shukla"
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@gmail.com"
    # SECURITY: this default is publicly known and dev-only. It MUST be overridden via env
    # outside development — the app refuses to bootstrap this default admin in staging/production
    # (see main.py `_ensure_default_admin`).
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin2402"

    # ── LLM — Primary (complex reasoning, document drafting, actions) ─────────
    LLM_PRIMARY_PROVIDER: str = "anthropic"
    LLM_PRIMARY_MODEL: str = "claude-sonnet-4-6"
    LLM_PRIMARY_MAX_TOKENS: int = 4096
    LLM_PRIMARY_TEMPERATURE: float = 0.3

    # Per-call LLM timeout (seconds). Bounds a hung provider so a single stalled call
    # cannot stall the whole request up to the client library's ~600s default. Set well
    # above a normal call (which takes a few seconds) so it never cuts a legitimate answer.
    LLM_REQUEST_TIMEOUT: int = 60

    # ── LLM — Fast (intent classification, simple queries) ────────────────────
    LLM_FAST_PROVIDER: str = "google"
    LLM_FAST_MODEL: str = "gemini/gemini-1.5-flash"
    LLM_FAST_MAX_TOKENS: int = 1024
    LLM_FAST_TEMPERATURE: float = 0.1

    # ── LLM — Fallback (if primary/fast fail) ─────────────────────────────────
    LLM_FALLBACK_PROVIDER: str = "openai"
    LLM_FALLBACK_MODEL: str = "gpt-4o-mini"
    LLM_FALLBACK_MAX_TOKENS: int = 2048
    LLM_FALLBACK_TEMPERATURE: float = 0.3

    # ── LLM API Keys ──────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    COHERE_API_KEY: str = ""

    # ── Embeddings ────────────────────────────────────────────────────────────
    EMBEDDING_PROVIDER: Literal["local", "openai", "cohere"] = "local"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_USE_FP16: bool = True
    EMBEDDING_MODEL_CACHE: str = "backend/models"
    # Device for the local embedding model: "auto" (GPU if available, else CPU), "cuda", "cpu".
    EMBEDDING_DEVICE: str = "auto"

    # ── Reranker ──────────────────────────────────────────────────────────────
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_TOP_K: int = 5
    # Cross-encoder reranking is O(candidates); 14 keeps strong recall for a top-5 result while
    # roughly halving the rerank compute vs 30 (a meaningful latency win on CPU rerankers).
    RERANKER_CANDIDATES: int = 14
    # Device for the reranker. On a small-VRAM GPU (≈4 GB) running BOTH the embedder and the
    # reranker on CUDA can OOM — set this to "cpu" to keep only the embedder on the GPU.
    RERANKER_DEVICE: str = "auto"

    # ── Postgres ──────────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "nipun_ai"
    POSTGRES_USER: str = "nipun"
    POSTGRES_PASSWORD: str = Field(min_length=8)
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10

    @computed_field
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field
    @property
    def postgres_dsn_sync(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 50

    # Cache TTLs (seconds)
    CACHE_SESSION_TTL: int = 604800       # 7 days
    CACHE_PROFILE_TTL: int = 2592000      # 30 days
    CACHE_LLM_RESPONSE_TTL: int = 3600    # 1 hour
    CACHE_TRANSLATION_TTL: int = 604800   # 7 days
    CACHE_MANDI_PRICES_TTL: int = 21600   # 6 hours
    CACHE_WEATHER_TTL: int = 14400        # 4 hours
    CACHE_LAW_SECTION_TTL: int = 2592000  # 30 days

    @computed_field
    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── Qdrant ────────────────────────────────────────────────────────────────
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""

    # TurboQuant / scalar quantization — int8 compression with full-precision
    # rescoring of top candidates. Cuts memory ~4x with negligible recall loss.
    QDRANT_QUANTIZATION_ENABLED: bool = True
    QDRANT_QUANTIZATION_ALWAYS_RAM: bool = True     # keep quantized vectors in RAM
    QDRANT_RESCORE_OVERSAMPLING: float = 2.0        # fetch N*oversampling, rescore full-precision

    # ── Neo4j knowledge graph (GraphRAG) ──────────────────────────────────────
    GRAPH_ENABLED: bool = False                     # turn on when Neo4j is running
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    GRAPH_ONLY_FOR_MULTIHOP: bool = True            # graph path used only for relational queries

    # ── Elasticsearch ─────────────────────────────────────────────────────────
    ELASTICSEARCH_HOST: str = "localhost"
    ELASTICSEARCH_PORT: int = 9200
    ELASTICSEARCH_USERNAME: str = ""
    ELASTICSEARCH_PASSWORD: str = ""

    @computed_field
    @property
    def elasticsearch_url(self) -> str:
        return f"http://{self.ELASTICSEARCH_HOST}:{self.ELASTICSEARCH_PORT}"

    # ── Memory ────────────────────────────────────────────────────────────────
    WORKING_MEMORY_MAX_TURNS: int = 20
    EPISODIC_MEMORY_RECALL_LIMIT: int = 5
    SEMANTIC_CACHE_SIMILARITY_THRESHOLD: float = 0.92

    # ── Retrieval ─────────────────────────────────────────────────────────────
    RETRIEVAL_DENSE_TOP_K: int = 100
    RETRIEVAL_SPARSE_TOP_K: int = 100
    RETRIEVAL_FINAL_TOP_K: int = 5
    RETRIEVAL_RRF_K: int = 60
    RETRIEVAL_SLOW_QUERY_MS: int = 150
    # Cross-lingual retrieval: BGE-M3 embeds all languages into ONE shared space, so a
    # Hindi query can match English/Tamil documents. All languages live in the same
    # per-domain collection, so this is a single search. When ON (default) no language
    # filter is applied (all languages considered); when OFF a `language` payload filter
    # restricts results to the query language. The answer is always written in the
    # user's language regardless.
    CROSS_LINGUAL_RETRIEVAL: bool = True

    # ── Auth ──────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24
    JWT_REFRESH_EXPIRY_DAYS: int = 30

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_LLM_PER_MINUTE: int = 20
    RATE_LIMIT_ACTION_PER_MINUTE: int = 5

    # ── Backpressure (global concurrency + hard request timeout) ──────────────
    # A cross-worker cap on simultaneously-processing queries so a traffic spike degrades
    # gracefully (a "busy, please retry" card) instead of collapsing the event loop / provider
    # quota. Redis-backed (ZSET of in-flight tokens, self-healing on crash), shared across all
    # workers/replicas. 0 disables the cap. Sized for the whole deployment, not per worker.
    MAX_INFLIGHT_QUERIES: int = 64
    INFLIGHT_SLOT_TTL: int = 40             # a crashed holder's slot self-expires after this (s)
    # Hard ceiling on a single query's end-to-end processing so nothing hangs a connection.
    REQUEST_HARD_TIMEOUT: int = 25

    # ── Dedicated thread pools (keep CPU-bound embed/rerank off the default executor) ──
    # Local embedding and reranking are CPU/GPU-bound; running them on the shared default
    # ThreadPoolExecutor let them starve each other (and every other run_in_executor call).
    # Small on purpose — the model saturates the device with a couple of workers; more thrash.
    EMBED_EXECUTOR_WORKERS: int = 2
    RERANK_EXECUTOR_WORKERS: int = 2

    # ── Languages ─────────────────────────────────────────────────────────────
    SUPPORTED_LANGUAGES: list[str] = ["en", "hi", "pa", "ta", "te", "mr", "gu"]
    DEFAULT_LANGUAGE: str = "hi"

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── External APIs ─────────────────────────────────────────────────────────
    AI4BHARAT_API_KEY: str = ""
    AI4BHARAT_API_BASE: str = "https://api.ai4bharat.org"
    DATA_GOV_IN_API_KEY: str = ""
    IMD_API_KEY: str = ""

    # ── Safety & Verification ─────────────────────────────────────────────────
    # Central verification/safety gate + intake safety pre-screen.
    SAFETY_PRESCREEN_ENABLED: bool = True           # tag intake for crisis/harm routes
    SAFETY_PRESCREEN_USE_LLM: bool = True           # refine rule tags with the fast LLM
    # GROUNDED-OR-ABSTAIN: below this aggregate confidence, the gate abstains and
    # points the user to an official channel instead of answering.
    CONFIDENCE_ABSTAIN_THRESHOLD: float = 0.5

    # ── Answer reliability scoring (DELIVER-WITH-SCORE, not block) ─────────────
    # We no longer DROP a good answer just because the knowledge base was thin.
    # Every answer is delivered with a calibrated multi-signal reliability score
    # (see src/safety/scoring.py); the UI marks low-reliability answers instead of
    # hiding them. Set ABSTAIN_ON_LOW_CONFIDENCE=True to restore the old hard block.
    ABSTAIN_ON_LOW_CONFIDENCE: bool = False
    # Band thresholds for the composite reliability score (0..1). At/above HIGH →
    # "reliable"; at/above WARN → "fairly reliable"; below WARN the UI warns the user
    # ("unsure of this answer"); below LOW → "unverified, treat with caution".
    RELIABILITY_HIGH_THRESHOLD: float = 0.75
    RELIABILITY_WARN_THRESHOLD: float = 0.5
    RELIABILITY_LOW_THRESHOLD: float = 0.3

    # ── Cross-source corroboration (triangulation) ────────────────────────────
    # When no single authoritative document backs a query, we check whether several
    # INDEPENDENT publishers (distinct hosts / tool families) state the same claims.
    # Strong agreement across independents lets an answer read as reliable even without
    # an official source — and lifts the "unverifiable" cap. Counted per publisher to
    # avoid false corroboration (many mirrors of one wrong origin = one witness).
    CORROBORATION_ENABLED: bool = True
    CORROBORATION_MIN_SOURCES: int = 3         # independent publishers for "confirmed"
    CORROBORATION_AGREEMENT_THRESHOLD: float = 0.66  # fraction of claims that must agree

    # ── Citation agent (answer-first, cite-after attribution) ─────────────────
    # Instead of only answering from what retrieval already found, the model may also
    # draw on well-established knowledge (see the hybrid grounding directive) — and the
    # citation agent then goes and FINDS a credible source for each claim it made,
    # folds those sources into the knowledge pool, and reports a citation-coverage score
    # (fraction of claims we could back with a source). This is what lets the assistant
    # answer beyond the DB without silently dropping to "no reliable source".
    CITATION_AGENT_ENABLED: bool = True
    CITATION_MAX_CLAIMS: int = 6           # cap claims we search sources for (bound cost)
    CITATION_COVERED_OVERLAP: float = 0.5  # claim already backed by existing knowledge if overlap ≥ this
    CITATION_MATCH_OVERLAP: float = 0.5    # a searched result supports a claim if overlap ≥ this
    CITATION_RESULTS_PER_CLAIM: int = 3    # top web results kept per claim search

    # ── Ask-back clarification (gather one-off details, don't store them) ──────
    # When a query is under-specified for a good, personalized answer (e.g. crop advice
    # with no location/land/soil) or a plan needs inputs, the assistant returns a
    # `clarify` card with a typed FORM asking only for what's missing — instead of
    # guessing, abstaining, or persisting rarely-used data in the DB. The submitted
    # answers are used for THAT turn only (folded into context), never stored unless the
    # user explicitly saves them to their profile.
    CLARIFY_ENABLED: bool = True
    CLARIFY_MAX_FIELDS: int = 4                      # never ask for more than this at once
    # Dynamic expert intake: when the fast deterministic slots don't apply, a fast-LLM
    # "expert" (senior doctor / advisor / research mentor, per domain) decides whether a
    # few targeted questions would materially improve the answer, and generates them.
    # This is what makes the assistant behave like a domain expert rather than a plain RAG
    # bot. Restricted to expertise-heavy domains to bound latency; always degrades to
    # "answer directly" on any error.
    CLARIFY_USE_LLM: bool = True
    # Every expertise domain gets the LLM expert-intake fallback when deterministic slots
    # don't fire. Only "general" (chit-chat / simple factual) is excluded to avoid friction.
    CLARIFY_LLM_DOMAINS: list[str] = [
        "health", "finance", "legal", "student", "career", "farming", "scheme",
        "jobs", "documents", "governance", "travel", "booking",
    ]

    # ── Reasoning (deliberate generation, not one-shot) ───────────────────────
    # REASONING_USE_PLAN folds the selected plan into the generator's prompt so the
    # answer follows the reasoned approach (the plan used to be computed then ignored).
    # REASONING_REFLECT_ENABLED runs ONE fast self-critique after a draft on non-trivial
    # (multi_step/action) queries: it checks the answer actually addresses the question and
    # is complete, and rewrites once if a concrete gap is found. The improved draft still
    # passes downstream claim verification, so it cannot introduce unsupported facts.
    REASONING_USE_PLAN: bool = True
    # OPT-IN quality passes (each adds one LLM call). OFF by default because the reviewer's
    # completeness check and the critic's high-stakes accuracy/safety check are baked into
    # the generation prompt (reasoning.quality_directive) at ZERO extra cost. Turn these on
    # to trade latency for an additional dedicated self-review / adversarial-critic pass.
    REASONING_REFLECT_ENABLED: bool = False
    CRITIC_ENABLED: bool = False
    CRITIC_DOMAINS: list[str] = ["health", "legal", "finance"]

    # ── Long-term user memory (Claude/ChatGPT-style persistent memories) ───────
    # Free-form salient facts the assistant learns across conversations, semantically
    # recalled into context each turn and fully user-manageable (view/add/edit/delete).
    MEMORY_ENABLED: bool = True
    MEMORY_RECALL_LIMIT: int = 6            # how many memories to inject per turn
    MEMORY_MAX_PER_USER: int = 200          # soft cap; oldest unpinned evicted beyond this
    MEMORY_DEDUP_SIMILARITY: float = 0.90   # ≥ this cosine → refresh existing, don't duplicate
    MEMORY_MAX_NEW_PER_TURN: int = 4        # cap memories learned from a single turn

    # ── Profile memory (learn durable facts from conversation, like Claude/GPT) ─
    # After a turn, a fast agent extracts stable, reusable facts the user stated about
    # themselves (state, occupation, land size, soil, crops…) and persists them durably
    # (fill-empty / union-merge — never clobbering an explicit profile edit) so the
    # assistant remembers you across sessions and stops re-asking. Runs in the background
    # after the answer is sent, so it never adds latency. Never stores transient details.
    PROFILE_MEMORY_ENABLED: bool = True

    # ── Agentic RAG loop ──────────────────────────────────────────────────────
    RAG_MAX_LOOPS: int = 3                          # max query rewrites before giving up
    RAG_SUFFICIENCY_MIN_CHUNKS: int = 1             # min relevant chunks to stop retrieving
    RAG_GRADE_USE_LLM: bool = True                  # fast-LLM relevance grading of chunks
    VERIFY_CLAIMS_USE_LLM: bool = True              # fast-LLM atomic-claim verification
    # NO-EVIDENCE handling: the gate must distinguish "the evidence contradicts the
    # answer" (→ abstain) from "we retrieved almost no evidence to check against"
    # (→ do NOT punish a good parametric answer to 0.0 and abstain). When the total
    # retrieved evidence is thinner than VERIFY_MIN_EVIDENCE_CHARS, verification is
    # "not verifiable from sources" and returns VERIFY_NO_EVIDENCE_CONFIDENCE instead
    # of marking every claim unsupported. When evidence IS present but at least one
    # claim is grounded, confidence is floored at VERIFY_PARTIAL_SUPPORT_FLOOR so a
    # couple of stray unsupported claims don't wrongly trigger abstention.
    VERIFY_MIN_EVIDENCE_CHARS: int = 240
    VERIFY_NO_EVIDENCE_CONFIDENCE: float = 0.5
    VERIFY_PARTIAL_SUPPORT_FLOOR: float = 0.5
    # Optional VERIFIED crisis helpline numbers. Empty by default — we never
    # hardcode unverified numbers. NALSA 15100 (legal aid) is the only baseline.
    # Fill these once verified, e.g. TELE_MANAS=14416, KIRAN=1800-599-0019.
    CRISIS_HELPLINE_MENTAL_HEALTH: str = ""         # e.g. Tele-MANAS (verify before use)
    CRISIS_HELPLINE_EMERGENCY: str = ""             # e.g. 112 / 108 (verify before use)
    NALSA_LEGAL_AID_HELPLINE: str = "15100"         # NALSA free legal aid (established)

    # ── Evaluation harness ────────────────────────────────────────────────────
    EVAL_GOLDEN_DIR: str = "src/eval/golden"        # dir of per-domain JSONL golden sets
    EVAL_RETRIEVAL_TOP_K: int = 5                   # k for precision@k on retrieval
    EVAL_USE_LLM_FAITHFULNESS: bool = True          # LLM-judge faithfulness (needs keys)

    # ── MCP tools + task execution ────────────────────────────────────────────
    # External capabilities are MCP tools. Read-only PREVIEW is always allowed;
    # real EXECUTION requires EXECUTION_ENABLED and explicit UI confirmation.
    EXECUTION_ENABLED: bool = False                 # master switch for real actions
    TASK_PREVIEW_ENABLED: bool = True               # read-only task assistants (previews)
    # Per-session circuit breakers on tool/agent call rates.
    CIRCUIT_BREAKER_TOOL_CALLS_PER_MIN: int = 20
    CIRCUIT_BREAKER_AGENT_CALLS_PER_MIN: int = 30
    # PREPARE→CONFIRM token TTL (seconds) — a prepared action must be confirmed within this.
    EXECUTION_CONFIRM_TTL: int = 600
    # External MCP tool API keys (empty → tool reports unavailable, degrades gracefully).
    INDIANKANOON_API_KEY: str = ""
    AGMARKNET_API_KEY: str = ""

    # ── Live-data tools (web search + credible sources) ───────────────────────
    # When the static index can't ground an answer, the orchestrator augments with
    # live web/credible-source tools, then grounds + cites the answer in them.
    WEB_TOOLS_ENABLED: bool = True                  # master switch for the live tool layer
    # Let an LLM choose WHICH data-source tools to call per query (vs a keyword table). Falls back
    # to the deterministic keyword selector if the LLM is unavailable. Adds one fast LLM call to a
    # live-augmented turn; set False to save that latency and use keyword selection only.
    LLM_TOOL_SELECTION: bool = True
    LIVE_AUGMENT_ENABLED: bool = True               # let the RAG loop pull live data when thin
    LIVE_HTTP_TIMEOUT: int = 8                       # seconds per outbound tool HTTP call (a straggler is skipped, not waited on)
    LIVE_AUGMENT_TIMEOUT: int = 6                     # overall wall-clock cap for the WHOLE live-tool fan-out; tools still running past this are dropped (their partial siblings are kept) so one slow upstream can't blow the latency budget
    LIVE_MAX_RESULTS: int = 5                        # results kept per tool
    LIVE_AUGMENT_MIN_CHUNKS: int = 2                 # augment when graded chunks fall below this
    # Inline images: real topic images come from an image-search API (SerpAPI / Google CSE). When
    # OFF (default), if no on-topic real image is found the marker is DROPPED rather than
    # AI-generating a stand-in (slow + can be off-topic). Turn ON only if you want generated art.
    INLINE_IMAGE_GENERATE: bool = False
    # Web search — Tavily is primary (best for LLM grounding); empty key falls back to
    # keyless sources (DuckDuckGo Instant Answer + Wikipedia). No key still works.
    TAVILY_API_KEY: str = ""
    BRAVE_API_KEY: str = ""
    SERPAPI_API_KEY: str = ""
    # Google Programmable Search (Custom Search JSON API) — enables Google web + IMAGE search.
    # Needs GOOGLE_API_KEY (already set for Gemini, with the Custom Search API enabled) AND a
    # Search-Engine ID (cx). When set, Google is used for grounding + topic images; keyless
    # sources (DuckDuckGo, Wikipedia) remain the fallback so search always works.
    GOOGLE_CSE_ID: str = ""
    # Finance — Yahoo Finance works keyless; Alpha Vantage optional for richer data.
    ALPHA_VANTAGE_API_KEY: str = ""
    # Research + books — all have keyless tiers; keys just raise rate limits.
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    GOOGLE_BOOKS_API_KEY: str = ""
    NEWSAPI_KEY: str = ""
    PUBMED_API_KEY: str = ""
    # Gmail / Google Drive — require the user's consented OAuth session. Empty client
    # config → the tools report they need consent (never handle raw credentials).
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_APPS_ENABLED: bool = False               # turn on once OAuth is wired

    # ── Book ingestion (download open full texts → local embeddings → Qdrant) ──
    # Only openly downloadable / public-domain sources (Project Gutenberg, Internet
    # Archive open texts, open-access PDFs). Copyrighted books are never downloaded —
    # only their metadata + where-to-borrow is shown.
    BOOKS_INGEST_ENABLED: bool = True
    BOOKS_AUTO_INGEST: bool = False                 # auto-enqueue on a books query (opt-in)
    BOOKS_INGEST_MAX: int = 2                        # max books ingested per topic run
    BOOKS_INGEST_DOMAIN: str = "student"            # Qdrant domain collection for book chunks
    BOOKS_MAX_DOWNLOAD_MB: int = 30                  # skip downloads larger than this

    # ── User document uploads (query against your own files, RBAC-isolated) ────
    UPLOAD_MAX_MB: int = 20                          # max size of a single uploaded file
    USER_DOC_QUOTA: int = 50                         # max documents a user may keep
    # Only OPEN licenses are downloaded + embedded; others are surfaced as find-it links.
    BOOKS_OPEN_LICENSES: list[str] = ["public_domain", "open_access", "cc", "creative_commons"]
    # Anna's Archive / Library Genesis — metadata/where-to-find search ONLY (they index
    # mostly copyrighted works). Key-gated + opt-in; never auto-downloads copyrighted books.
    ANNAS_ARCHIVE_ENABLED: bool = False
    ANNAS_ARCHIVE_API_KEY: str = ""
    ANNAS_ARCHIVE_BASE: str = "https://annas-archive.org"
    LIBGEN_METADATA_ENABLED: bool = False           # LibGen metadata search (find-it only)

    # ── A2A (optional specialist agents) ──────────────────────────────────────
    A2A_ENABLED: bool = False
    A2A_SIGNING_SECRET: str = ""                    # HMAC secret for signing Agent Cards
    A2A_TRUSTED_AGENTS: list[str] = []              # allowlist of trusted agent ids
    A2A_TOKEN_TTL: int = 300                        # short-lived M2M token TTL (seconds)

    # ── RLM research agent (long documents) ───────────────────────────────────
    RLM_MAX_DEPTH: int = 3                          # recursion depth bound
    RLM_MAX_SUBCALLS: int = 12                      # total child LLM calls bound
    RLM_CHUNK_CHARS: int = 4000                     # variable-inspection chunk size

    # ── Observability ─────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    PROMETHEUS_PORT: int = 9090
    # Structured (machine-parseable) file output. When ON, every structured log file
    # (app.log, error.log, the subsystem files, chat.log …) is written as one JSON object
    # per line — ready for log aggregators (ELK / Loki / Datadog / CloudWatch). When OFF
    # (default) those files use the readable pipe-delimited format. The human-readable
    # views (flow.log, ipa.log narration, terminal heartbeat) stay plain text either way.
    LOG_JSON: bool = False
    # Attach the call site (module:function:line) to every structured record. Invaluable
    # when debugging — you see exactly which line emitted each event. Small overhead; ON.
    LOG_CALLSITE: bool = True
    # Chat-flow tracing — write the ACTUAL data flowing through each step (query text,
    # LLM prompts + responses, retrieved chunks, agent output, final card) to the
    # dedicated chat.log so the whole request can be replayed end-to-end.
    # (Env-var keys keep the LOG_FLOW_* names for backward compatibility.)
    # SECURITY DEFAULTS: flow tracing stays ENABLED (step/event skeleton) but content bodies
    # are OFF by default so full request/response bodies and LLM prompts are NOT written to disk
    # unless explicitly opted in. Set LOG_FLOW_CONTENT=true (+ LOG_FLOW_TRUNCATE=false) locally
    # for full end-to-end replay.
    LOG_FLOW_ENABLED: bool = True
    LOG_FLOW_CONTENT: bool = False                   # OFF: no content bodies (keys/counts only) unless opted in
    # Line-length cap for any content that IS logged when content is enabled.
    LOG_CONTENT_MAX_CHARS: int = 24000              # truncate any single logged value to this
    # Default ON: when content logging IS enabled, cap line length so prompts/responses don't
    # blow up the log. Set LOG_FLOW_TRUNCATE=false locally to capture COMPLETE, untruncated bodies.
    LOG_FLOW_TRUNCATE: bool = True                    # when True, cap flow-trace values at LOG_CONTENT_MAX_CHARS

    # Console/terminal readability. The terminal shows ONLY a clean heartbeat of API + LLM
    # calls (TERMINAL_ENABLED); the full human-readable per-request flow (query → steps →
    # answer) is written to flow.log (FLOW_CONSOLE_ENABLED). All structured detail still goes
    # to app.log / chat.log for monitoring and debugging.
    TERMINAL_ENABLED: bool = True
    FLOW_CONSOLE_ENABLED: bool = True
    # The readable per-TASK browser-run story (goal → each step → each action/hand-off →
    # result) written to ipa.log — the IPA parallel to flow.log. Structured ipa.* detail
    # always goes to ipa.debug.log / app.log regardless of this toggle.
    IPA_CONSOLE_ENABLED: bool = True

    # IPA browser agent. When ON, a browser-automatable task (book / apply / fill-on-site /
    # search-and-act) is handed to the live browser agent — which collects all inputs in ONE
    # form and EXECUTES the task step by step with a live view — instead of returning a static
    # plan or a chat clarification card. File deliverables (make a ppt/doc) still generate inline.
    IPA_ENABLED: bool = True
    # Device surface — local file actions. OFF by default and SANDBOXED: even when enabled the
    # agent may only read/write/list files inside DEVICE_SANDBOX_DIR, never run shell commands or
    # touch anything outside it. Full user-device control (open apps, OS automation) intentionally
    # requires a separate, explicitly-installed local companion — not this server process.
    DEVICE_EXECUTION_ENABLED: bool = False
    DEVICE_SANDBOX_DIR: str = ""                      # empty → <backend>/device_sandbox

    # Per-request token + latency metering. Records tokens/latency for every LLM call,
    # attributes each to its pipeline step, and reports per-step + total breakdowns.
    METERING_ENABLED: bool = True
    METRICS_IN_RESPONSE: bool = True                 # attach the metrics summary to the response card

    # ── External-key sanitisation ─────────────────────────────────────────────
    # An env value like `DATA_GOV_IN_API_KEY=   # Agmarknet mandi prices` can be read
    # verbatim (comment included) by some .env parsers, producing a junk "key" that is
    # truthy but invalid → 403s on every call. Real API keys are single tokens with no
    # whitespace and never start with '#'. We blank anything that fails that shape so
    # the owning tool cleanly reports "not configured" and degrades instead of erroring.
    _SANITISE_KEY_FIELDS = (
        "DATA_GOV_IN_API_KEY", "IMD_API_KEY", "AGMARKNET_API_KEY", "AI4BHARAT_API_KEY",
        "INDIANKANOON_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "SERPAPI_API_KEY",
        "ALPHA_VANTAGE_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "GOOGLE_BOOKS_API_KEY",
        "NEWSAPI_KEY", "PUBMED_API_KEY", "ANNAS_ARCHIVE_API_KEY",
    )

    # Actual output dimension per embedding model — the Qdrant collections and every
    # query vector MUST use this exact size. A mismatch (e.g. collections built at 1024
    # while the embedder emits 1536) makes EVERY vector search fail silently and fall back
    # to weak results. We derive the truth from the configured model, not a stale constant.
    _EMBED_DIMS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
        "bge-m3": 1024,
        "bge-large": 1024,
        "embed-multilingual-v3.0": 1024,
        "embed-english-v3.0": 1024,
    }

    @model_validator(mode="after")
    def _sync_embedding_dim(self) -> "Settings":
        import structlog

        model = (self.EMBEDDING_MODEL or "").split("/")[-1].lower()
        expected = next((d for k, d in self._EMBED_DIMS.items() if k in model), None)
        if expected is None and self.EMBEDDING_PROVIDER == "local":
            expected = 1024  # BGE-M3 default
        if expected and expected != self.EMBEDDING_DIM:
            structlog.get_logger("config").warning(
                "embedding_dim_autocorrected", configured=self.EMBEDDING_DIM,
                actual=expected, provider=self.EMBEDDING_PROVIDER, model=self.EMBEDDING_MODEL)
            object.__setattr__(self, "EMBEDDING_DIM", expected)
        return self

    @model_validator(mode="after")
    def _sanitise_external_keys(self) -> "Settings":
        import structlog

        _log = structlog.get_logger("config")
        for field in self._SANITISE_KEY_FIELDS:
            value = getattr(self, field, "") or ""
            cleaned = value.strip()
            # Strip a trailing inline comment left by the .env parser, then re-validate.
            if "#" in cleaned:
                cleaned = cleaned.split("#", 1)[0].strip()
            if cleaned and (" " in cleaned or "\t" in cleaned or value.strip().startswith("#")):
                _log.warning("invalid_api_key_ignored", field=field,
                             reason="value looks like a comment/placeholder, not a key")
                cleaned = ""
            if cleaned != value:
                object.__setattr__(self, field, cleaned)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
