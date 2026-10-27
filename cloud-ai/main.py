"""
AutoSort IoT - Cloud AI Inference Service
Supports real ONNX Runtime inference (YOLO11n Classification) with graceful mock fallback.
Uses single-thread CPU inference for small cloud instances.
"""

import base64
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import numpy as np
from PIL import Image, UnidentifiedImageError

if __package__:
    from .inference import classification_probabilities, preprocess_image_bytes
else:
    from inference import classification_probabilities, preprocess_image_bytes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("autosort-ai")

app = FastAPI(
    title="AutoSort IoT - Cloud AI Service",
    description="Kumquat classification service with YOLO11 ONNX Runtime & fallback mode",
    version="1.0.0",
)

# Enable CORS for local and cross-origin dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Dashboard frontend if exists
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

# In-Memory Session Storage for Web Monitoring Dashboard
active_sessions: List[dict] = []
current_session_id: Optional[str] = None


def init_session() -> dict:
    global current_session_id
    now = datetime.now()
    s_id = f"SES-{now.strftime('%Y%m%d')}-01"
    session = {
        "id": s_id,
        "name": f"Phiên #01 — {now.strftime('%d/%m/%Y')}",
        "startTime": now.isoformat(),
        "endTime": None,
        "status": "RUNNING",
        "fruits": [],
    }
    active_sessions.append(session)
    current_session_id = s_id
    return session


def get_current_session() -> dict:
    if not active_sessions:
        return init_session()
    return active_sessions[-1]


def record_fruit_to_session(infer_result: dict, image_bytes: Optional[bytes] = None) -> dict:
    session = get_current_session()
    now_iso = datetime.now().isoformat()

    img_data_url = "samples/ripe_1.jpg"
    if image_bytes and len(image_bytes) < 300_000:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        img_data_url = f"data:image/jpeg;base64,{b64}"

    label = infer_result.get("label", "REJECT")
    servo_action = (
        "Gạt Cổng 1 (Green)"
        if label == "GREEN"
        else ("Gạt Cổng 2 (Ripe)" if label == "RIPE" else "Trôi Cuối (Reject)")
    )

    fruit_record = {
        "id": infer_result.get("fruit_id", "F0000"),
        "sessionId": session["id"],
        "label": label,
        "confidence": infer_result.get("confidence", 0.0),
        "timestamp": now_iso,
        "inferenceMs": infer_result.get("inference_ms", 0.0),
        "image": img_data_url,
        "decisionReason": infer_result.get("decision_reason", "CLASSIFIED"),
        "servoAction": servo_action,
    }
    session["fruits"].append(fruit_record)
    return fruit_record


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


@app.post("/infer")
async def infer(
    fruit_id: str = Form(...),
    camera_id: str = Form(...),
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
        record_fruit_to_session(mock_result, content)
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
        record_fruit_to_session(real_result, content)
        return real_result
    except Exception as e:
        logger.error("Inference failure for fruit_id=%s: %s", fruit_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


# --- SESSION MANAGEMENT ENDPOINTS FOR MONITORING DASHBOARD ---
@app.get("/api/session/current")
def get_current_session_endpoint():
    """Retrieve active session state, metrics and fruit list for Live Monitor."""
    return get_current_session()


@app.get("/api/sessions")
def list_sessions_endpoint():
    """Retrieve all stored session summaries for Session History selector."""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "startTime": s["startTime"],
            "endTime": s["endTime"],
            "status": s["status"],
            "fruitCount": len(s["fruits"]),
        }
        for s in active_sessions
    ]


@app.get("/api/sessions/{session_id}")
def get_session_detail_endpoint(session_id: str):
    """Retrieve full details and fruit records of a specific session."""
    for s in active_sessions:
        if s["id"] == session_id:
            return s
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/new")
def new_session_endpoint():
    """Start a new sorting session."""
    global current_session_id
    now = datetime.now()
    if active_sessions:
        active_sessions[-1]["endTime"] = now.isoformat()
        active_sessions[-1]["status"] = "COMPLETED"

    next_idx = len(active_sessions) + 1
    s_id = f"SES-{now.strftime('%Y%m%d')}-{next_idx:02d}"
    session = {
        "id": s_id,
        "name": f"Phiên #{next_idx:02d} — {now.strftime('%d/%m/%Y')}",
        "startTime": now.isoformat(),
        "endTime": None,
        "status": "RUNNING",
        "fruits": [],
    }
    active_sessions.append(session)
    current_session_id = s_id
    return session

