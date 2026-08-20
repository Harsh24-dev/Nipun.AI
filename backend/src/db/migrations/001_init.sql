-- Nipun.AI — Initial Schema
-- Run via: make migrate
-- Requires: pgvector extension (included in pgvector/pgvector:pg16 Docker image)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone       TEXT UNIQUE NOT NULL,              -- encrypted at rest in app layer
    language    TEXT NOT NULL DEFAULT 'hi',
    state       TEXT,
    district    TEXT,
    occupation  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);

-- ── User Profiles (extended preferences) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    preferences     JSONB NOT NULL DEFAULT '{}',
    active_schemes  TEXT[] DEFAULT '{}',
    land_size_acres NUMERIC(10, 2),
    soil_type       TEXT,
    current_crops   TEXT[],
    last_lat        DOUBLE PRECISION,
    last_lon        DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Sessions ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    language    TEXT NOT NULL,
    domain      TEXT,
    turn_count  INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at DESC);

-- ── Conversation Logs ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_logs (
    id              UUID NOT NULL DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL,
    user_id         UUID NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    language        TEXT,
    domain          TEXT,
    tokens_used     INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Partitions — one per quarter (add more as needed)
CREATE TABLE IF NOT EXISTS conversation_logs_2025_q1
    PARTITION OF conversation_logs FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2025_q2
    PARTITION OF conversation_logs FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2025_q3
    PARTITION OF conversation_logs FOR VALUES FROM ('2025-07-01') TO ('2025-10-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2025_q4
    PARTITION OF conversation_logs FOR VALUES FROM ('2025-10-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2026_q1
    PARTITION OF conversation_logs FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2026_q2
    PARTITION OF conversation_logs FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2026_q3
    PARTITION OF conversation_logs FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS conversation_logs_2026_q4
    PARTITION OF conversation_logs FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');

CREATE INDEX IF NOT EXISTS idx_conv_logs_session ON conversation_logs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_logs_user    ON conversation_logs(user_id, created_at DESC);

-- ── Episodic Memory ───────────────────────────────────────────────────────────
-- Stores LLM-generated summaries of past sessions, searchable by vector
CREATE TABLE IF NOT EXISTS episodic_memory (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id  UUID REFERENCES sessions(id) ON DELETE SET NULL,
    summary     TEXT NOT NULL,
    embedding   vector(1024),              -- BGE-M3 dense vector
    domain      TEXT,
    language    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodic_user    ON episodic_memory(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_domain  ON episodic_memory(user_id, domain);
-- IVFFlat index for ANN search (build after data volume reaches 10k+ rows)
-- CREATE INDEX ON episodic_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── Task History ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_history (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL,
    correlation_id  TEXT NOT NULL,
    domain          TEXT NOT NULL,
    intent          TEXT,
    query           TEXT NOT NULL,
    language        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    response_card   JSONB,
    llm_model       TEXT,
    tokens_used     INT,
    duration_ms     INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_task_user       ON task_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_corr       ON task_history(correlation_id);
CREATE INDEX IF NOT EXISTS idx_task_domain     ON task_history(domain, created_at DESC);

-- ── Document Index (ingestion dedup) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS document_index (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_url      TEXT NOT NULL,
    source_hash     TEXT NOT NULL,          -- SHA-256 of content for dedup
    domain          TEXT NOT NULL,
    language        TEXT NOT NULL,
    title           TEXT,
    chunk_count     INT NOT NULL DEFAULT 0,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified   TIMESTAMPTZ,
    UNIQUE (source_url, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_doc_domain ON document_index(domain, language);

-- ── User Feedback ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID,
    task_id         UUID REFERENCES task_history(id) ON DELETE SET NULL,
    correlation_id  TEXT,
    rating          SMALLINT CHECK (rating IN (-1, 1)),   -- -1 thumbs down, +1 thumbs up
    comment         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Data Retention (auto-delete old conversation logs) ───────────────────────
-- Run via cron: SELECT delete_old_conversation_logs();
CREATE OR REPLACE FUNCTION delete_old_conversation_logs() RETURNS void AS $$
BEGIN
    DELETE FROM conversation_logs WHERE created_at < NOW() - INTERVAL '90 days';
END;
$$ LANGUAGE plpgsql;
