-- Nipun.AI — Persist the full set of user profile preferences
-- Appearance/UI + onboarding fields that were previously kept only in the
-- browser's localStorage are now stored server-side so they sync across devices.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ui_preset       TEXT    NOT NULL DEFAULT 'sampann',
    ADD COLUMN IF NOT EXISTS motif           TEXT    NOT NULL DEFAULT 'minimal',
    ADD COLUMN IF NOT EXISTS text_scale      TEXT    NOT NULL DEFAULT 'M',
    ADD COLUMN IF NOT EXISTS high_contrast   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS voice_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS festive_accents BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS age_band        TEXT,
    ADD COLUMN IF NOT EXISTS gender          TEXT,
    ADD COLUMN IF NOT EXISTS languages_known TEXT[]  NOT NULL DEFAULT '{}';
