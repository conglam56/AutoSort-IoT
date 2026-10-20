"""QuatSort IoT Cloud AI service (mock stage; no trained AI model yet)."""

import logging
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

app = FastAPI(title="QuatSort IoT - Cloud AI Service", version="0.1.0")
MAX_IMAGE_BYTES = 1_000_000

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quat-sort-ai")


@app.get("/health")
def health():
    return {"status": "ok", "service": "quat-sort-ai", "mode": "mock", "model_version": "mock-v0"}


@app.post("/infer")
async def infer(
    fruit_id: str = Form(...),
    camera_id: str = Form(...),
    image: UploadFile = File(...),
):
    """Verify JPEG upload and JSON reply; replace with YOLO inference later."""
    if image.content_type not in ("image/jpeg", "image/jpg"):
        raise HTTPException(status_code=415, detail="Only image/jpeg is supported")
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 1 MB or smaller")
    if not content.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=400, detail="Invalid JPEG data")
    logger.info("MOCK received fruit_id=%s camera_id=%s image_bytes=%s", fruit_id, camera_id, len(content))
    return {
        "fruit_id": fruit_id,
        "camera_id": camera_id,
        "label": "MOCK",
        "confidence": 0.0,
        "model_version": "mock-v0",
        "image_bytes": len(content),
        "note": "Image received; AI inference not implemented yet",
    }
