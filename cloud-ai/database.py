"""PostgreSQL persistence; transactions protect session rollover and fruit inserts."""
import base64
import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

if __package__:
    from . import config
else:
    import config


def connect():
    tls = {"sslmode": config.DATABASE_SSLMODE} if config.DATABASE_SSLMODE else {}
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, connect_timeout=5, **tls)


def check_database():
    with connect() as db:
        if not db.execute("SELECT version FROM schema_version WHERE version = 2").fetchone():
            raise RuntimeError("Run python manage.py init-db to initialize or migrate the API database")


def audit(db, action, user_id=None, ip="local"):
    db.execute("INSERT INTO audit_logs(user_id, action, ip_address) VALUES (%s,%s,%s)", (user_id, action, ip))


def lock_sorting(db):
    # Same lock across processes, including inference and an administrator's rollover.
    db.execute("SELECT pg_advisory_xact_lock(83417001)")


def current_row(db):
    row = db.execute("SELECT * FROM sorting_sessions WHERE status = 'RUNNING'").fetchone()
    if row:
        return row
    now = datetime.now(timezone.utc)
    return db.execute(
        "INSERT INTO sorting_sessions(id,name,status) VALUES (%s,%s,'RUNNING') RETURNING *",
        (uuid4(), "Phiên " + now.astimezone().strftime("%d/%m/%Y %H:%M")),
    ).fetchone()


def serialize_session(row):
    return {"id": str(row["id"]), "name": row["name"], "startTime": row["start_time"].isoformat(),
            "endTime": row["end_time"].isoformat() if row["end_time"] else None, "status": row["status"]}


def detail(db, row):
    session = serialize_session(row)
    fruits = db.execute("SELECT * FROM fruit_results WHERE session_id=%s ORDER BY sequence", (row["id"],)).fetchall()
    session["fruits"] = [{"id": f["fruit_id"], "recordId": str(f["sequence"]), "cameraId": f["camera_id"],
                          "sessionId": str(f["session_id"]), "label": f["label"], "confidence": f["confidence"],
                          "timestamp": f["recorded_at"].isoformat(), "inferenceMs": f["inference_ms"],
                          "image": f["image"], "decisionReason": f["decision_reason"],
                          "modelVersion": f["model_version"], "servoAction": f["servo_action"]} for f in fruits]
    return session


def get_current_session():
    with connect() as db:
        row = db.execute("SELECT * FROM sorting_sessions WHERE status='RUNNING'").fetchone()
        return detail(db, row) if row else None


def list_sessions():
    with connect() as db:
        rows = db.execute("""SELECT s.*, count(f.sequence) AS fruit_count FROM sorting_sessions s
                             LEFT JOIN fruit_results f ON f.session_id=s.id
                             GROUP BY s.id ORDER BY s.start_time""").fetchall()
        return [{**serialize_session(row), "fruitCount": row["fruit_count"]} for row in rows]


def get_session(session_id):
    try:
        value = UUID(session_id)
    except ValueError:
        return None
    with connect() as db:
        row = db.execute("SELECT * FROM sorting_sessions WHERE id=%s", (value,)).fetchone()
        return detail(db, row) if row else None


def new_session(user_id, ip):
    with connect() as db:
        return start_session(db, user_id, ip)


def start_session(db, user_id, ip):
    lock_sorting(db)
    db.execute("UPDATE sorting_sessions SET status='COMPLETED',end_time=now() WHERE status='RUNNING'")
    row = current_row(db)
    audit(db, "session.created", user_id, ip)
    return detail(db, row)


def record_fruit_to_session(result, image_bytes=None):
    with connect() as db:
        return insert_fruit(db, result, image_bytes)


def insert_fruit(db, result, image_bytes=None):
    image = ""
    if image_bytes and len(image_bytes) < 300_000:
        image = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
    action = {"GREEN": "Gạt Cổng 1 (Green)", "RIPE": "Gạt Cổng 2 (Ripe)",
              "REJECT": "Trôi Cuối (Reject)", "MOCK": "Không điều khiển · MOCK"}[result["label"]]
    lock_sorting(db)
    session = current_row(db)
    return db.execute("""INSERT INTO fruit_results(session_id,fruit_id,camera_id,label,confidence,
                      inference_ms,image,decision_reason,model_version,servo_action)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING sequence""",
                   (session["id"], result["fruit_id"], result["camera_id"], result["label"], result["confidence"],
                    result["inference_ms"], image, result["decision_reason"], result["model_version"], action)).fetchone()["sequence"]


class InferenceConflict(ValueError):
    """The same request key was reused for a different fruit, camera or image."""


def record_inference_once(request_key, fruit_id, camera_id, image_bytes, classify):
    """Commit the response and fruit together; retries survive restarts/rollovers."""
    fingerprint = hashlib.sha256(image_bytes).hexdigest()
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(83417004, hashtext(%s))", (request_key,))
        previous = db.execute("SELECT image_sha256,response FROM inference_requests WHERE request_key=%s", (request_key,)).fetchone()
        if previous:
            response = previous["response"]
            if (previous["image_sha256"] != fingerprint or response["fruit_id"] != fruit_id
                    or response["camera_id"] != camera_id):
                raise InferenceConflict("Idempotency key belongs to different input")
            return response
        response = {**classify(), "request_id": request_key}
        sequence = insert_fruit(db, response, image_bytes)
        db.execute("INSERT INTO inference_requests(request_key,image_sha256,result_id,response) VALUES (%s,%s,%s,%s)",
                   (request_key, fingerprint, sequence, Jsonb(response)))
        return response
