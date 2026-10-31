"""Bound camera-driver calls in a child process; never block the Serial owner."""
import multiprocessing
import os
from pathlib import Path
import threading
import time

from bridge import BridgeError, MAX_IMAGE_BYTES


def encode_frame(frame):
    import cv2
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 1:
        raise ValueError("Invalid frame")
    height, width = frame.shape[:2]
    if height * width > 25_000_000:
        raise ValueError("Frame too large")
    scale = min(1.0, 1600 / max(height, width))
    if scale < 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    for quality in (90, 80, 65, 45):
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and 0 < jpeg.size <= MAX_IMAGE_BYTES:
            return jpeg.tobytes()
    raise ValueError("JPEG too large")


def camera_worker(connection, source, index, backend, video_path, warmup_seconds=1.5):
    """One capture handle. Webcams drain continuously; files advance per request."""
    capture = None
    try:
        os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
        import cv2
        cv2.setNumThreads(1)
        api = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}[backend]
        if source != "video" and api != cv2.CAP_ANY and not cv2.videoio_registry.hasBackend(api):
            connection.send(("error", "BACKEND_UNAVAILABLE"))
            return
        capture = cv2.VideoCapture(video_path if source == "video" else index,
                                   cv2.CAP_ANY if source == "video" else api)
        if not capture.isOpened():
            connection.send(("error", "OPEN_FAILED"))
            return
        # Virtual cameras can initially produce their "Start DroidCam" splash frame.
        # Drain startup frames once; all work remains inside the parent's deadline.
        ready_at = time.monotonic() + (warmup_seconds if source == "webcam" else 0)
        # Consume pending request BEFORE reading, so a previous frame is never reused.
        while True:
            if source == "video" or (time.monotonic() >= ready_at and connection.poll()):
                command = connection.recv()
                if command == "close":
                    return
                ok, frame = capture.read()
                if not ok:
                    connection.send(("error", "END_OF_VIDEO" if source == "video" else "CAMERA_LOST"))
                    return
                connection.send(("frame", encode_frame(frame)))
            else:
                ok, _ = capture.read()
                if not ok:
                    if time.monotonic() < ready_at:
                        time.sleep(.02)
                        continue
                    connection.send(("error", "CAMERA_LOST"))
                    return
                time.sleep(.002)
    except (Exception, KeyboardInterrupt):
        # Do not expose filenames, device URLs, native exception text or frames in logs.
        try:
            connection.send(("error", "CAPTURE_FAILED"))
        except (OSError, EOFError):
            pass
    finally:
        if capture is not None:
            capture.release()
        connection.close()


class LocalCamera:
    def __init__(self, settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._process = self._connection = None
        self._closed = False

    def _start(self):
        context = multiprocessing.get_context("spawn")
        connection, child = context.Pipe()
        video_path = str(Path(self.settings.video_path).resolve()) if self.settings.camera_source == "video" else ""
        process = context.Process(target=camera_worker, args=(child, self.settings.camera_source,
                                  self.settings.camera_index, self.settings.camera_backend, video_path,
                                  self.settings.camera_warmup), daemon=True)
        try:
            process.start()
        except Exception as error:
            connection.close()
            self._closed = True
            raise BridgeError("Không khởi động được nguồn camera cục bộ.") from error
        finally:
            child.close()
        self._process, self._connection = process, connection

    def capture(self, deadline):
        deadline = min(deadline, time.monotonic() + self.settings.capture_timeout)
        if not self._lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise BridgeError("Nguồn camera đang bận hoặc đã hết thời gian chụp.")
        try:
            if self._closed:
                raise BridgeError("Nguồn camera đã đóng/lỗi; kiểm tra nguồn và chạy lại bridge.")
            if time.monotonic() >= deadline:
                raise BridgeError("Hết thời gian chụp ảnh.")
            if self._process is None:
                self._start()
            self._connection.send("capture")
            if not self._connection.poll(max(0, deadline - time.monotonic())):
                raise BridgeError("Camera quá hạn; đã ngắt tiến trình lấy ảnh. Kiểm tra và chạy lại bridge.")
            kind, payload = self._connection.recv()
            if kind != "frame":
                if payload == "BACKEND_UNAVAILABLE":
                    raise BridgeError("Bản OpenCV hiện tại thiếu backend camera đã chọn. Windows cần opencv-python trong requirements, không dùng đồng thời bản headless.")
                if payload == "END_OF_VIDEO":
                    raise BridgeError("Đã hết video mẫu; không tự lặp lại ảnh. Chạy lại để thử từ đầu.")
                raise BridgeError("Không mở/đọc được camera. Kiểm tra DroidCam, camera index và quyền camera.")
            if time.monotonic() >= deadline or not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_IMAGE_BYTES:
                raise BridgeError("Ảnh camera không hợp lệ hoặc đến quá hạn.")
            return payload
        except (OSError, EOFError) as error:
            self._shutdown()
            raise BridgeError("Mất kết nối tiến trình camera; chạy lại bridge sau khi kiểm tra.") from error
        except BridgeError:
            self._shutdown()
            raise
        finally:
            self._lock.release()

    def _shutdown(self):
        self._closed = True
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=.3)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=.3)
        if self._connection is not None:
            self._connection.close()
        self._process = self._connection = None

    def close(self):
        # Another worker may be finishing an old run: its own deadline is bounded.
        with self._lock:
            self._shutdown()
