-- Initial schema. Apply explicitly with: python manage.py init-db
CREATE TABLE IF NOT EXISTS schema_version (
    version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app_users (
    id uuid PRIMARY KEY,
    username varchar(64) UNIQUE NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('admin', 'viewer')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    csrf_token text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS login_limits (
    bucket text PRIMARY KEY,
    attempts integer NOT NULL DEFAULT 0,
    window_start timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sorting_sessions (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    start_time timestamptz NOT NULL DEFAULT now(),
    end_time timestamptz,
    status text NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_session ON sorting_sessions(status) WHERE status = 'RUNNING';
CREATE TABLE IF NOT EXISTS fruit_results (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES sorting_sessions(id),
    fruit_id varchar(128) NOT NULL,
    camera_id varchar(128) NOT NULL,
    label text NOT NULL CHECK (label IN ('GREEN', 'RIPE', 'REJECT', 'MOCK')),
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    inference_ms double precision NOT NULL,
    image text NOT NULL DEFAULT '',
    decision_reason text NOT NULL,
    model_version text NOT NULL,
    servo_action text NOT NULL
);
CREATE INDEX IF NOT EXISTS fruit_results_session ON fruit_results(session_id, sequence);
-- Additive v2 migration: persisted receipts for safe Camera Bridge retries.
CREATE TABLE IF NOT EXISTS inference_requests (
    request_key varchar(128) PRIMARY KEY,
    image_sha256 char(64) NOT NULL,
    result_id bigint UNIQUE NOT NULL REFERENCES fruit_results(sequence) ON DELETE CASCADE,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid REFERENCES app_users(id) ON DELETE SET NULL,
    action text NOT NULL,
    ip_address text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;
INSERT INTO schema_version(version) VALUES (2) ON CONFLICT DO NOTHING;
