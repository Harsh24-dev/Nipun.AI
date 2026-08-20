-- Nipun.AI — User profile fields, roles, and admin support

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role        TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    ADD COLUMN IF NOT EXISTS is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS bio         TEXT,
    ADD COLUMN IF NOT EXISTS interests   TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS ai_model    TEXT NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS theme       TEXT NOT NULL DEFAULT 'saffron';

-- Rename 'title' on sessions if it does not exist yet (safe no-op otherwise)
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title TEXT;

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role) WHERE role = 'admin';
