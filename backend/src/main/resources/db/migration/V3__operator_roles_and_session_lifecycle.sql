-- Executed inside the startup transaction after schema v2 exists. No data deletion.
SELECT pg_advisory_xact_lock(83417003);
SELECT pg_advisory_xact_lock(83417001);
CREATE TABLE IF NOT EXISTS legacy_viewer_quarantine (
    user_id uuid PRIMARY KEY REFERENCES app_users(id),
    previous_active boolean NOT NULL,
    quarantined_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO legacy_viewer_quarantine(user_id,previous_active)
SELECT id,active FROM app_users WHERE role='viewer' ON CONFLICT DO NOTHING;
DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM app_users WHERE role='viewer');
UPDATE app_users SET active=false WHERE role='viewer';
-- An inactive legacy value is retained ONLY for quarantine, never as an application role.
ALTER TABLE app_users DROP CONSTRAINT IF EXISTS app_users_role_check;
ALTER TABLE app_users ADD CONSTRAINT app_users_role_check
CHECK (role IN ('admin','operator') OR (role='viewer' AND NOT active));
CREATE TABLE IF NOT EXISTS session_requests (
    request_key varchar(128) PRIMARY KEY,
    operation text NOT NULL CHECK (operation IN ('start','end')),
    session_id uuid NOT NULL REFERENCES sorting_sessions(id),
    actor_id uuid NOT NULL REFERENCES app_users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_version(version) VALUES (3) ON CONFLICT DO NOTHING;
ALTER TABLE fruit_results ALTER COLUMN recorded_at SET DEFAULT clock_timestamp();
