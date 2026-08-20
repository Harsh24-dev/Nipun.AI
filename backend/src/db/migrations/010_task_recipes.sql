-- Reusable task recipes learned from successfully executed IPA runs.
-- These store the HOW of a task (checklist + the generalized, successful action sequence on a
-- site) — NOT any user's personal values, which stay private in that user's profile. A recipe
-- recorded by one user therefore lets the agent execute a SIMILAR task for ANY other user faster
-- and more reliably. Personal data is never written here (the up-front form already excludes
-- credentials/OTP/payment, and action values are stored as field-name placeholders).

CREATE TABLE IF NOT EXISTS task_recipes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host          TEXT NOT NULL,            -- site the task ran on (e.g. www.irctc.co.in)
    goal          TEXT NOT NULL,            -- example goal that produced this recipe
    keywords      TEXT NOT NULL DEFAULT '', -- normalized goal keywords for matching
    start_url     TEXT NOT NULL,
    steps         JSONB NOT NULL,           -- the checklist
    trace         JSONB NOT NULL,           -- generalized successful action sequence
    form_fields   JSONB NOT NULL DEFAULT '[]'::jsonb,  -- inputs the task needs
    created_by    UUID,                     -- first author (internal only; never exposed to others)
    success_count INT  NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_task_recipes_host ON task_recipes (host);
CREATE INDEX IF NOT EXISTS idx_task_recipes_updated ON task_recipes (updated_at DESC);
