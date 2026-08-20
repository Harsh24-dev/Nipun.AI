-- Nipun.AI — Auth credentials migration
-- Adds email/password support alongside phone-based auth

ALTER TABLE users
    ALTER COLUMN phone DROP NOT NULL;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS name          TEXT,
    ADD COLUMN IF NOT EXISTS email         TEXT,
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;
