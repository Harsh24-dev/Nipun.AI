-- Nipun.AI — Persist onboarding completion server-side.
-- Previously onboarding-done was only a per-browser localStorage flag, so a returning user on
-- a fresh device/browser was forced through onboarding again. This flag is the source of truth,
-- synced across devices. Existing users who already have profile data are backfilled to TRUE so
-- they are not re-onboarded.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS onboarded BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill: treat anyone who already set a state or age band (i.e. onboarded before this flag
-- existed) as onboarded, so the change doesn't re-prompt existing users.
UPDATE users SET onboarded = TRUE
 WHERE onboarded = FALSE AND (state IS NOT NULL OR age_band IS NOT NULL);
