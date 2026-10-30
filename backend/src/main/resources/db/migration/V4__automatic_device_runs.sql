-- Additive migration; existing sessions/results remain intact.
SELECT pg_advisory_xact_lock(83417001);
CREATE TABLE IF NOT EXISTS device_runs (
    run_id uuid PRIMARY KEY,
    camera_id varchar(128) NOT NULL,
    mode text NOT NULL CHECK (mode IN ('CONVEYOR','MANUAL_TEST')),
    session_id uuid UNIQUE REFERENCES sorting_sessions(id),
    last_seen timestamptz NOT NULL DEFAULT clock_timestamp(),
    ended_at timestamptz,
    end_reason text
);
ALTER TABLE sorting_sessions ADD COLUMN IF NOT EXISTS device_run_id uuid UNIQUE REFERENCES device_runs(run_id);
ALTER TABLE sorting_sessions ADD COLUMN IF NOT EXISTS end_reason text;
INSERT INTO schema_version(version) VALUES (4) ON CONFLICT DO NOTHING;
