-- Nipun.AI — Durable service tasks (form-assist + booking lifecycle).
-- Lets a task be TRACKED to completion ("do it on my behalf until my trip is done"):
-- the agent fills the form, the user completes payment/OTP, and the task is followed
-- through submitted → in_progress → completed. Additive + idempotent.

CREATE TABLE IF NOT EXISTS service_tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      UUID,
    service         TEXT NOT NULL,                 -- rti | train_booking | doctor_appointment | ...
    title           TEXT NOT NULL,
    -- Lifecycle. The agent fills; the user does payment/OTP; then it is tracked.
    --   gathering     → still collecting details
    --   filled        → form auto-filled, ready for the user's review
    --   awaiting_user → waiting on the user's payment / OTP / e-sign
    --   submitted     → user completed their part; submitted to the portal
    --   in_progress   → being processed (e.g. trip upcoming, application under review)
    --   completed | cancelled | failed
    status          TEXT NOT NULL DEFAULT 'gathering'
                    CHECK (status IN ('gathering','filled','awaiting_user','submitted',
                                      'in_progress','completed','cancelled','failed')),
    -- Auto-filled fields ONLY. Credentials are never stored (enforced in app layer).
    filled          JSONB NOT NULL DEFAULT '{}',
    -- The steps left to the user (payment/OTP/password) — never done by the agent.
    remaining_steps JSONB NOT NULL DEFAULT '[]',
    -- Free-form follow-up state (e.g. PNR, appointment id, next reminder time).
    tracking        JSONB NOT NULL DEFAULT '{}',
    due_at          TIMESTAMPTZ,                   -- when to next check / remind
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_tasks_user   ON service_tasks(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_tasks_active ON service_tasks(status, due_at)
    WHERE status IN ('awaiting_user','submitted','in_progress');
