-- Planner + task execution audit
-- Adds the chosen Plan to task_history and an append-only audit log for actions.

-- Persist the plan the orchestrator chose for a query.
ALTER TABLE task_history ADD COLUMN IF NOT EXISTS plan JSONB;

-- Allow the 'planned' and execution lifecycle statuses.
-- (status is a free-text TEXT column with a default 'pending'; no enum to alter.)

-- Append-only audit trail for PREPARE -> CONFIRM -> EXECUTE -> AUDIT.
CREATE TABLE IF NOT EXISTS task_audit (
    id             UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id        UUID,                          -- optional link to task_history(id)
    user_id        UUID         NOT NULL,
    correlation_id TEXT         NOT NULL,
    tool           TEXT         NOT NULL,          -- MCP tool / integration name
    phase          TEXT         NOT NULL,          -- prepare | confirm | execute | audit | reject
    payload        JSONB,                          -- redacted request/preview (never raw credentials)
    result         JSONB,                          -- redacted result
    status         TEXT         NOT NULL DEFAULT 'ok',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_audit_corr ON task_audit(correlation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_task_audit_user ON task_audit(user_id, created_at DESC);
