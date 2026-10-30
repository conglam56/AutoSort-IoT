SELECT pg_advisory_xact_lock(83417001);
CREATE TABLE IF NOT EXISTS station_state (
    id integer PRIMARY KEY CHECK (id=1),
    agent_id uuid,
    camera_id varchar(128),
    last_seen timestamptz,
    reported text NOT NULL DEFAULT 'OFFLINE' CHECK(reported IN ('OFFLINE','IDLE','RUNNING','PAUSED','FAULT')),
    run_id uuid,
    revision bigint NOT NULL DEFAULT 0
);
INSERT INTO station_state(id) VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS station_commands (
    id uuid PRIMARY KEY,
    request_key varchar(128) UNIQUE NOT NULL,
    actor_id uuid NOT NULL REFERENCES app_users(id),
    request_revision bigint NOT NULL,
    agent_id uuid NOT NULL,
    run_id uuid NOT NULL,
    action text NOT NULL CHECK(action IN ('START','PAUSE','RESUME','STOP')),
    status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DELIVERED','SUCCEEDED','FAILED')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '15 seconds',
    detail text,
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS station_command_pending ON station_commands(created_at) WHERE status IN ('PENDING','DELIVERED');
INSERT INTO schema_version(version) VALUES(5) ON CONFLICT DO NOTHING;
