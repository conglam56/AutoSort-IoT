"""
AutoSort IoT - Cloud AI Inference Service
Supports real ONNX Runtime inference (YOLO11n Classification) with graceful mock fallback.
Uses single-thread CPU inference for small cloud instances.
"""

from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import time
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
import psycopg
import numpy as np
from PIL import Image, UnidentifiedImageError

if __package__:
    from .inference import classification_probabilities, preprocess_image_bytes
    from . import admin, auth, config, database
else:
    from inference import classification_probabilities, preprocess_image_bytes
    import auth
    import admin
    import config
    import database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autosort-ai")

@asynccontextmanager
async def lifespan(app):
    config.validate_config()
    await run_in_threadpool(database.check_database)
    yield


app = FastAPI(
    title="AutoSort IoT - Cloud AI Service",
    description="Kumquat classification service with YOLO11 ONNX Runtime & fallback mode",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(auth.router)
app.include_router(admin.router)

# Enable CORS for local and cross-origin dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-API-Key"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith(("/api/", "/infer")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(psycopg.Error)
async def database_unavailable(request, exc):
    logger.error("PostgreSQL operation failed (%s)", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable. Please try again"})

# Mount Dashboard frontend if exists
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

record_fruit_to_session = database.record_fruit_to_session


MAX_IMAGE_BYTES = 1_000_000  # 1 MB max upload limit
MODEL_DIR = Path(__file__).parent / "model"
ONNX_PATH = MODEL_DIR / "best.onnx"
CLASSES_PATH = MODEL_DIR / "classes.json"

# Global model state
ort_session = None
input_name: Optional[str] = None
model_version: str = "yolo11n-cls-kumquat-v1"
confidence_threshold: float = 0.70
img_size: int = 224
classes_list: List[str] = ["GREEN", "REJECT", "RIPE"]
idx_to_class: Dict[str, str] = {"0": "GREEN", "1": "REJECT", "2": "RIPE"}
model_ready: bool = False


def load_model():
    """Attempt to load ONNX model and classes metadata. Fallback to mock mode if absent."""
    global ort_session, input_name, model_version, confidence_threshold, img_size
    global classes_list, idx_to_class, model_ready

    if not ONNX_PATH.exists():
        logger.warning("ONNX model file not found at %s. Service will run in MOCK mode.", ONNX_PATH)
        model_ready = False
        return

    try:
        import onnxruntime as ort

        # Load metadata if classes.json exists
        if CLASSES_PATH.exists():
            with open(CLASSES_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
                model_version = meta.get("model_version", model_version)
                confidence_threshold = float(meta.get("threshold", confidence_threshold))
                img_size = int(meta.get("imgsz", img_size))
                classes_list = meta.get("classes", classes_list)
                idx_to_class = meta.get("idx_to_class", {str(i): c for i, c in enumerate(classes_list)})
            logger.info("Loaded metadata from %s: classes=%s, threshold=%.2f", CLASSES_PATH, classes_list, confidence_threshold)
        else:
            logger.warning("classes.json not found at %s. Using default classes %s", CLASSES_PATH, classes_list)

        # Limit CPU parallelism for small cloud instances.
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        ort_session = ort.InferenceSession(str(ONNX_PATH), sess_options=opts, providers=["CPUExecutionProvider"])
        input_name = ort_session.get_inputs()[0].name
        model_ready = True
        logger.info("ONNX Runtime session initialized successfully with %s (input: %s)", ONNX_PATH, input_name)
    except Exception as e:
        logger.error("Failed to initialize ONNX Runtime session: %s. Falling back to MOCK mode.", e, exc_info=True)
        model_ready = False


# Initialize model at startup
load_model()


@app.get("/", include_in_schema=False)
def dashboard_home():
    return RedirectResponse("/dashboard/")


@app.get("/ready", include_in_schema=False)
def ready():
    """Cloud readiness checks PostgreSQL as well as the running web process."""
    database.check_database()
    return {"status": "ready", "model_ready": model_ready}


@app.get("/health")
def health():
    """Health check endpoint exposing runtime mode and model status."""
    return {
        "status": "ok",
        "service": "quat-sort-ai",
        "mode": "onnx" if model_ready else "mock",
        "model_ready": model_ready,
        "classes": classes_list if model_ready else ["MOCK"],
        "model_version": model_version if model_ready else "mock-v0",
        "threshold": confidence_threshold if model_ready else 0.0,
    }


@app.post("/infer", dependencies=[Depends(auth.require_device)])
async def infer(
    fruit_id: str = Form(..., min_length=1, max_length=128),
    camera_id: str = Form(..., min_length=1, max_length=128),
    image: UploadFile = File(...),
):
    """
    Perform fruit classification inference on uploaded JPEG.
    Uses ONNX Runtime when available; otherwise falls back to MOCK.
    """
    if image.content_type not in ("image/jpeg", "image/jpg"):
        raise HTTPException(status_code=415, detail="Only image/jpeg is supported")

    content = await image.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 1 MB or smaller")
    if not content.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=400, detail="Invalid JPEG data")

    # Fallback mode if ONNX model is not available
    if not model_ready or ort_session is None:
        logger.info("MOCK mode: received fruit_id=%s, camera_id=%s, bytes=%s", fruit_id, camera_id, len(content))
        mock_result = {
            "fruit_id": fruit_id,
            "camera_id": camera_id,
            "label": "MOCK",
            "raw_label": "MOCK",
            "confidence": 0.0,
            "decision_reason": "MOCK_MODE",
            "model_version": "mock-v0",
            "image_bytes": len(content),
            "inference_ms": 0.0,
            "note": "AI model not ready on server; running in mock fallback mode",
        }
        await run_in_threadpool(record_fruit_to_session, mock_result, content)
        return mock_result

    # Real ONNX inference
    t_start = time.perf_counter()
    try:
        tensor = preprocess_image_bytes(content, target_size=img_size)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise HTTPException(status_code=400, detail="Invalid JPEG data") from e

    try:
        raw_outputs = ort_session.run(None, {input_name: tensor})
        probs = classification_probabilities(raw_outputs[0], len(classes_list))

        best_idx = int(np.argmax(probs))
        confidence = float(probs[best_idx])
        raw_label = idx_to_class.get(str(best_idx), f"CLASS_{best_idx}")

        # Safety decision rule: if confidence is under threshold, mark as REJECT
        # Compare in the output dtype so float32(0.70) meets a 0.70 threshold.
        threshold = float(np.asarray(confidence_threshold, dtype=probs.dtype))
        if confidence < threshold:
            label = "REJECT"
            decision_reason = "LOW_CONFIDENCE"
        else:
            label = raw_label
            decision_reason = "CLASSIFIED"

        inference_ms = (time.perf_counter() - t_start) * 1000.0

        logger.info(
            "INFER: fruit_id=%s camera_id=%s -> raw=%s conf=%.4f final=%s reason=%s (%.1f ms)",
            fruit_id,
            camera_id,
            raw_label,
            confidence,
            label,
            decision_reason,
            inference_ms,
        )

        real_result = {
            "fruit_id": fruit_id,
            "camera_id": camera_id,
            "label": label,
            "raw_label": raw_label,
            "confidence": round(confidence, 4),
            "decision_reason": decision_reason,
            "model_version": model_version,
            "image_bytes": len(content),
            "inference_ms": round(inference_ms, 2),
        }
    except Exception as e:
        logger.error("Inference failure for fruit_id=%s: %s", fruit_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Inference failed") from e
    await run_in_threadpool(record_fruit_to_session, real_result, content)
    return real_result


# --- SESSION MANAGEMENT ENDPOINTS FOR MONITORING DASHBOARD ---
@app.get("/api/session/current", dependencies=[Depends(auth.current_user)])
def get_current_session_endpoint():
    """Retrieve active session state, metrics and fruit list for Live Monitor."""
    return database.get_current_session()


@app.get("/api/sessions", dependencies=[Depends(auth.current_user)])
def list_sessions_endpoint():
    """Retrieve all stored session summaries for Session History selector."""
    return database.list_sessions()


@app.get("/api/sessions/{session_id}", dependencies=[Depends(auth.current_user)])
def get_session_detail_endpoint(session_id: str):
    """Retrieve full details and fruit records of a specific session."""
    session = database.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/sessions/new")
def new_session_endpoint(request: Request, user=Depends(auth.require_admin)):
    """Start a new sorting session."""
    with database.connect() as db:
        auth.lock_authenticated_user(db, user, admin=True)
        return database.start_session(db, user["id"], auth.client_ip(request))


@app.get("/api/audit-logs", dependencies=[Depends(auth.require_admin_read)])
def audit_logs_endpoint():
    with database.connect() as db:
        return db.execute("""SELECT a.id,a.action,a.ip_address,a.created_at,u.username
                             FROM audit_logs a LEFT JOIN app_users u ON u.id=a.user_id
                             ORDER BY a.id DESC LIMIT 100""").fetchall()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(Path(__file__).parent))


