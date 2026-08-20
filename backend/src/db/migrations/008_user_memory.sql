-- Nipun.AI — Long-term user memory (Claude/ChatGPT-style)
-- Free-form, salient facts the assistant learns about a user ACROSS conversations, so it
-- personalizes and stops re-asking. Distinct from:
--   * episodic_memory  → summaries of whole past sessions
--   * user_profiles    → fixed, structured columns that drive domain logic
-- These are short natural-language memories ("Preparing for UPSC 2026", "Prefers Hindi"),
-- semantically recalled into context and fully user-manageable (view / add / edit / delete).

CREATE TABLE IF NOT EXISTS user_memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'fact',   -- fact | preference | goal | context
    -- Dimension-agnostic on purpose: a bare `vector` accepts whatever the configured
    -- embedder emits (1536 for OpenAI, 1024 for BGE), so we never hit the dimension
    -- mismatch that silently breaks fixed-size columns. Per-user counts are small, so a
    -- sequential cosine scan is fine (no ANN index needed).
    embedding       vector,
    source_session  UUID REFERENCES sessions(id) ON DELETE SET NULL,
    pinned          BOOLEAN NOT NULL DEFAULT FALSE, -- always injected + never auto-evicted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_memories_user ON user_memories(user_id, updated_at DESC);
