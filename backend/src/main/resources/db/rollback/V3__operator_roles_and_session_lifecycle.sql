-- Stop all v3 writers before applying. Run explicitly with psql ON_ERROR_STOP=1.
-- This downgrade never grants access: operator/legacy viewer accounts stay locked.
BEGIN;
SELECT pg_advisory_xact_lock(83417002);
SELECT pg_advisory_xact_lock(83417003);
SELECT pg_advisory_xact_lock(83417001);
DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM app_users WHERE role IN ('operator','viewer'));
UPDATE app_users SET role='viewer',active=false WHERE role IN ('operator','viewer');
ALTER TABLE app_users DROP CONSTRAINT app_users_role_check;
ALTER TABLE app_users ADD CONSTRAINT app_users_role_check CHECK (role IN ('admin','viewer'));
DELETE FROM schema_version WHERE version=3;
ALTER TABLE fruit_results ALTER COLUMN recorded_at SET DEFAULT now();
-- Keep quarantine metadata, request receipts, accounts, results and audit history.
COMMIT;
