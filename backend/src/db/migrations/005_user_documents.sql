-- Nipun.AI — User document uploads + rich corpus metadata
--
-- 1. user_documents: files a user uploads to query against. RBAC is enforced by
--    owner_id: a user only ever sees / queries their own documents. The actual
--    chunk vectors live in the single `user_documents` Qdrant collection, always
--    filtered by owner_id at query time.
-- 2. Rich metadata columns on document_index for better citation + filtered retrieval.

-- ── User-uploaded documents ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_documents (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Session-scoped uploads: a doc uploaded inside a chat session is used only for
    -- that session's queries, and its chunks are purged when the session is deleted.
    -- NULL session_id = an account-wide document (persists across sessions).
    session_id    UUID REFERENCES sessions(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    filename      TEXT,
    mime_type     TEXT,
    source_hash   TEXT,                         -- SHA-256 of content (per-owner dedup)
    language      TEXT NOT NULL DEFAULT 'en',
    domain        TEXT,                         -- auto-classified or user-provided
    subject       TEXT,
    level         TEXT,                         -- beginner|intermediate|advanced|academic
    author        TEXT,
    status        TEXT NOT NULL DEFAULT 'processing',  -- processing|ready|failed
    chunk_count   INT NOT NULL DEFAULT 0,
    size_bytes    BIGINT,
    visibility    TEXT NOT NULL DEFAULT 'private',     -- private|shared (future)
    error         TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_user_docs_owner   ON user_documents(owner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_docs_status  ON user_documents(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_user_docs_session ON user_documents(session_id);

-- ── Rich metadata for the public/book corpus (better citations + filtering) ─────
ALTER TABLE document_index
    ADD COLUMN IF NOT EXISTS book_id          TEXT,
    ADD COLUMN IF NOT EXISTS author           TEXT,
    ADD COLUMN IF NOT EXISTS subject          TEXT,
    ADD COLUMN IF NOT EXISTS level            TEXT,
    ADD COLUMN IF NOT EXISTS publication_year INT,
    ADD COLUMN IF NOT EXISTS visibility       TEXT NOT NULL DEFAULT 'public',
    ADD COLUMN IF NOT EXISTS metadata         JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_doc_subject ON document_index(domain, subject);
CREATE INDEX IF NOT EXISTS idx_doc_book    ON document_index(book_id);
