"""Phone JPEG / DroidCam webcam -> Cloud AI -> USB Serial ESP32 controller."""
import argparse
from dataclasses import dataclass
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
import requests
import serial
from bridge_errors import BridgeError

LOG = logging.getLogger("autosort-bridge")
LABELS = frozenset({"GREEN", "RIPE", "REJECT"})
MAX_IMAGE_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 16_384
CONTROLLER_MAX_JOB_SECONDS = 25.0  # Firmware 30s AI watchdog leaves margin for PC/Serial.
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Settings:
    phone_url: str
    api_key: str
    serial_port: str = ""
    cloud_url: str = "https://autosort-iot-java.onrender.com/infer"
    camera_id: str = "phone_cam01"
    baud_rate: int = 115200
    capture_timeout: float = 5.0
    request_timeout: float = 5.0
    job_timeout: float = 20.0
    startup_timeout: float = 90.0
    attempts: int = 3
    state_path: Path = Path(__file__).parent / ".local" / "bridge-state.sqlite3"
    camera_source: str = "phone"
    camera_index: int = 0
    camera_backend: str = "auto"
    video_path: str = ""
    camera_warmup: float = 1.5

    @classmethod
    def from_environment(cls, manual=False, camera_only=False):
        try:
            settings = cls(
                phone_url=os.getenv("PHONE_IP_WEBCAM_URL", ""), api_key=os.getenv("DEVICE_API_KEY", ""),
                serial_port=os.getenv("SERIAL_PORT", ""), cloud_url=os.getenv("CLOUD_INFER_URL", cls.cloud_url),
                camera_id=os.getenv("CAMERA_ID", "phone_cam01"), baud_rate=int(os.getenv("SERIAL_BAUD_RATE", "115200")),
                capture_timeout=float(os.getenv("CAPTURE_TIMEOUT_SECONDS", "5")),
                request_timeout=float(os.getenv("CLOUD_REQUEST_TIMEOUT_SECONDS", "5")),
                job_timeout=float(os.getenv("JOB_TIMEOUT_SECONDS", "20")),
                startup_timeout=float(os.getenv("STARTUP_TIMEOUT_SECONDS", "90")),
                attempts=int(os.getenv("CLOUD_MAX_ATTEMPTS", "3")),
                state_path=Path(os.getenv("BRIDGE_STATE_PATH", str(cls.state_path))),
                camera_source=os.getenv("CAMERA_SOURCE", "phone"),
                camera_index=int(os.getenv("CAMERA_INDEX", "0")),
                camera_backend=os.getenv("CAMERA_BACKEND", "auto"),
                video_path=os.getenv("CAMERA_VIDEO_PATH", ""),
                camera_warmup=float(os.getenv("CAMERA_WARMUP_SECONDS", "1.5")),
            )
        except ValueError as error:
            raise BridgeError("Cấu hình số không hợp lệ trong camera-bridge/.env.") from error
        if settings.camera_source not in {"phone", "webcam", "video"}:
            raise BridgeError("CAMERA_SOURCE phải là phone, webcam hoặc video.")
        if not 0 <= settings.camera_index <= 64 or settings.camera_backend not in {"auto", "dshow", "msmf"}:
            raise BridgeError("CAMERA_INDEX phải trong 0–64; CAMERA_BACKEND là auto, dshow hoặc msmf.")
        if (not math.isfinite(settings.camera_warmup) or not 0 <= settings.camera_warmup <= 10
                or (settings.camera_source == "webcam" and settings.camera_warmup >= settings.capture_timeout)):
            raise BridgeError("CAMERA_WARMUP_SECONDS phải trong 0–10 giây và nhỏ hơn CAPTURE_TIMEOUT_SECONDS khi dùng webcam.")
        if settings.camera_source == "video":
            if not manual:
                raise BridgeError("Video chỉ dùng xem trước hoặc --manual, không dùng để điều khiển băng chuyền.")
            if not settings.video_path or not Path(settings.video_path).is_file():
                raise BridgeError("CAMERA_VIDEO_PATH phải trỏ tới file video có sẵn.")
        urls = [("cloud", settings.cloud_url)] if not camera_only else []
        if settings.camera_source == "phone":
            urls.append(("phone", settings.phone_url))
        for name, value in urls:
            try:
                parts = urlsplit(value)
                valid = parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username and not parts.password
                if name == "cloud":
                    valid = valid and not parts.query and not parts.fragment
                    valid = valid and (parts.scheme == "https" or parts.hostname in {"127.0.0.1", "localhost"})
            except ValueError:
                valid = False
            if not valid:
                raise BridgeError("Cần URL ảnh điện thoại HTTP/HTTPS và URL cloud HTTPS (HTTP chỉ cho localhost); không đặt mật khẩu trong URL.")
        if (not camera_only and (not settings.api_key or len(settings.api_key) < 32 or settings.api_key.startswith("replace_"))
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", settings.camera_id)):
            raise BridgeError("Cần DEVICE_API_KEY riêng tối thiểu 32 ký tự và CAMERA_ID hợp lệ.")
        if not manual and not camera_only and not settings.serial_port:
            raise BridgeError("Cần SERIAL_PORT; dùng --manual để kiểm tra khi không có ESP32.")
        durations = (settings.capture_timeout, settings.request_timeout, settings.job_timeout, settings.startup_timeout)
        if (not all(math.isfinite(v) and 0 < v <= 300 for v in durations)
                or not 1 <= settings.attempts <= 5 or not 1 <= settings.baud_rate <= 2_000_000):
            raise BridgeError("Timeout phải trong (0, 300] giây, số lần thử 1–5 và baud rate hợp lệ.")
        return settings


def response_json(response):
    """Bound even malformed/proxy responses, rather than logging their bodies."""
    data = bytearray()
    for chunk in response.iter_content(4096):
        data.extend(chunk)
        if len(data) > MAX_RESPONSE_BYTES:
            raise BridgeError("Phản hồi cloud vượt giới hạn.")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise BridgeError("Cloud không trả JSON hợp lệ.") from error
    if not isinstance(result, dict):
        raise BridgeError("Cloud không trả đối tượng kết quả hợp lệ.")
    return result


class PhoneCamera:
    def __init__(self, settings, session):
        self.settings, self.session = settings, session

    def close(self):
        pass  # HTTP session lifetime belongs to the caller.

    def capture(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BridgeError("Hết thời gian chụp ảnh.")
        try:
            with self.session.get(self.settings.phone_url, stream=True, allow_redirects=False,
                                  timeout=min(self.settings.capture_timeout, remaining)) as response:
                if response.status_code != 200:
                    raise BridgeError("Không lấy được ảnh từ điện thoại.")
                content = bytearray()
                for chunk in response.iter_content(16_384):
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES or time.monotonic() >= deadline:
                        raise BridgeError("Ảnh vượt 1 MB hoặc đã hết thời gian chụp.")
        except requests.RequestException as error:
            raise BridgeError("Mất kết nối hoặc timeout camera điện thoại.") from error
        try:
            if not content.startswith(b"\xff\xd8"):
                raise ValueError("Not JPEG")
            with Image.open(io.BytesIO(content)) as image:
                if image.format != "JPEG" or image.width * image.height > 25_000_000:
                    raise ValueError("Unsupported image")
                image.load()
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise BridgeError("Điện thoại chưa trả ảnh JPEG hợp lệ (tối đa 25 megapixel).") from error
        return bytes(content)


def create_camera(settings, session):
    if settings.camera_source == "phone":
        return PhoneCamera(settings, session)
    from local_camera import LocalCamera
    return LocalCamera(settings)


class CloudAI:
    def __init__(self, settings, session):
        self.settings, self.session = settings, session
        self.run_id = None

    def check_ready(self):
        """Wake the Free service before the controller starts waiting for a fruit."""
        parts = urlsplit(self.settings.cloud_url)
        base = parts.path.rsplit("/", 1)[0]
        deadline = time.monotonic() + self.settings.startup_timeout
        try:
            for path in ("ready", "health"):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BridgeError("Cloud chưa sẵn sàng trong thời gian khởi động.")
                url = urlunsplit((parts.scheme, parts.netloc, base + "/" + path, "", ""))
                with self.session.get(url, timeout=remaining, stream=True, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise BridgeError("Cloud/database chưa sẵn sàng. Chưa nhận quả.")
                    payload = response_json(response)
                if path == "ready" and payload.get("status") != "ready":
                    raise BridgeError("Database chưa sẵn sàng. Chưa nhận quả.")
                if path == "health" and (payload.get("mode") != "onnx" or payload.get("model_ready") is not True
                                         or payload.get("idempotency_supported") is not True):
                    raise BridgeError("Cloud cần model ONNX thật và API hỗ trợ chống trùng. Chưa nhận quả.")
        except requests.RequestException as error:
            raise BridgeError("Không kết nối được cloud trong bước khởi động.") from error

    def classify(self, image, fruit_id, request_id, deadline):
        for attempt in range(self.settings.attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            retry_after = 0.5 * 2 ** attempt
            try:
                with self.session.post(
                    self.settings.cloud_url, data={"fruit_id": fruit_id, "camera_id": self.settings.camera_id},
                    files={"image": ("fruit.jpg", image, "image/jpeg")},
                    headers={"X-API-Key": self.settings.api_key, "Idempotency-Key": request_id,
                             **({"X-Run-Id": self.run_id} if self.run_id else {})},
                    timeout=min(self.settings.request_timeout, remaining), stream=True, allow_redirects=False,
                ) as response:
                    if response.status_code == 200:
                        result = response_json(response)
                        if time.monotonic() >= deadline:
                            raise BridgeError("Kết quả cloud đến quá hạn; không dùng để điều khiển.")
                        return self.validate(result, fruit_id, request_id)
                    if response.status_code not in TRANSIENT_STATUS:
                        raise BridgeError(f"Cloud từ chối yêu cầu (HTTP {response.status_code}); không gửi lại.")
                    try:
                        retry_after = max(retry_after, float(response.headers.get("Retry-After", "0")))
                        if not math.isfinite(retry_after):
                            raise ValueError("Invalid Retry-After")
                    except ValueError:
                        retry_after = 0.5 * 2 ** attempt
            except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
                pass  # The previous POST may have committed: reuse its exact key, IDs and image.
            except requests.RequestException as error:
                raise BridgeError("Lỗi giao tiếp cloud; không có kết quả điều khiển hợp lệ.") from error
            if attempt + 1 < self.settings.attempts and time.monotonic() + retry_after < deadline:
                time.sleep(retry_after)
            else:
                break
        raise BridgeError("Cloud không trả kết quả trong ngân sách thời gian/số lần thử.")

    def validate(self, result, fruit_id, request_id):
        confidence = result.get("confidence")
        valid_confidence = type(confidence) in {int, float} and 0 <= confidence <= 1 and math.isfinite(confidence)
        label, reason = result.get("label"), result.get("decision_reason")
        if (result.get("fruit_id") != fruit_id or result.get("camera_id") != self.settings.camera_id
                or (self.run_id is not None and result.get("run_id") != self.run_id)
                or result.get("request_id") != request_id or not isinstance(label, str) or label not in LABELS or not valid_confidence
                or not isinstance(result.get("model_version"), str) or not result["model_version"]
                or result["model_version"].lower().startswith("mock")
                or not isinstance(reason, str) or reason not in {"CLASSIFIED", "LOW_CONFIDENCE"}
                or (reason == "LOW_CONFIDENCE" and label != "REJECT")
                or (reason == "CLASSIFIED" and result.get("raw_label") != label)):
            raise BridgeError("Kết quả cloud sai mã quả, MOCK hoặc không hợp lệ; không dùng nhãn này để điều khiển.")
        return label


class DeviceRun:
    """One process run owns one cloud session; retries reuse its UUID."""
    def __init__(self, settings, session, manual=False):
        self.settings, self.session = settings, session
        self.id = str(uuid4())
        self.mode = "MANUAL_TEST" if manual else "CONVEYOR"
        self.attempted = False
        self.last_beat = 0.0
        self._stop = threading.Event()
        self._thread = None
        self._heartbeat_error = False

    def call(self, action, reason=None):
        parts = urlsplit(self.settings.cloud_url)
        prefix = parts.path.rsplit("/", 1)[0]
        url = urlunsplit((parts.scheme, parts.netloc, prefix + f"/device/runs/{self.id}/{action}", "", ""))
        payload = {"cameraId": self.settings.camera_id}
        if action != "heartbeat": payload["mode"] = self.mode
        if reason: payload["reason"] = reason
        for attempt in range(2 if action != "heartbeat" else 1):
            try:
                with self.session.post(url, json=payload, headers={"X-API-Key": self.settings.api_key},
                                       timeout=3, stream=True, allow_redirects=False) as response:
                    if response.status_code == 200:
                        result = response_json(response)
                        if result.get("runId") != self.id or result.get("status") not in {"RUNNING", "COMPLETED"}:
                            raise BridgeError("Phản hồi phiên tự động không hợp lệ.")
                        if action != "stop" and result["status"] != "RUNNING":
                            raise BridgeError("Lượt chạy đã kết thúc; không tự mở lại.")
                        if action == "stop" and result["status"] != "COMPLETED":
                            raise BridgeError("Cloud chưa xác nhận kết thúc lượt chạy.")
                        self.last_beat = time.monotonic()
                        return result
                    if response.status_code not in TRANSIENT_STATUS:
                        raise BridgeError("Không mở/cập nhật được phiên tự động. Cần API schema v4; nếu còn phiên cũ, đóng phiên đó trước.")
            except requests.RequestException:
                pass
            if attempt == 0 and action != "heartbeat": time.sleep(.25)
        raise BridgeError("Mất kết nối quản lý phiên tự động.")

    def start(self):
        self.attempted = True
        return self.call("start")

    def heartbeat(self):
        if self._heartbeat_error:
            raise BridgeError("Phiên thử ảnh đã mất kết nối cloud; khởi động lại bridge để tạo lượt mới.")
        if self._thread is not None: return
        if time.monotonic() - self.last_beat >= 10:
            self.call("heartbeat")

    def keep_manual_alive(self):
        # input() blocks in --manual; use a dedicated run HTTP session, never the inference session.
        def loop():
            while not self._stop.wait(10):
                try: self.call("heartbeat")
                except BridgeError:
                    self._heartbeat_error = True
                    return
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self, reason):
        self._stop.set()
        if self._thread is not None: self._thread.join(timeout=4)
        if self.attempted: self.call("stop", reason)


class EventJournal:
    """Claim controller event IDs durably before work; never replay a servo write."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            camera_id TEXT NOT NULL, trigger_id TEXT NOT NULL, request_id TEXT NOT NULL,
            status TEXT NOT NULL, label TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(camera_id,trigger_id))""")
        self.db.commit()

    def claim(self, camera_id, trigger_id):
        request_id = uuid4().hex
        row = self.db.execute("INSERT OR IGNORE INTO events(camera_id,trigger_id,request_id,status) VALUES (?,?,?,'processing')",
                              (camera_id, trigger_id or "legacy-" + request_id, request_id))
        self.db.commit()
        return request_id if row.rowcount else None

    def finish(self, request_id, label):
        self.db.execute("UPDATE events SET status='sent',label=? WHERE request_id=?", (label, request_id))
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def parse_trigger(line):
    """None means legacy trigger; an empty string means unrelated serial output."""
    if line == "TRIGGER":
        return None
    if re.fullmatch(r"TRIGGER:[A-Za-z0-9_.:-]{1,96}", line):
        return line.removeprefix("TRIGGER:")
    return ""


def process_trigger(trigger_id, settings, camera, cloud, journal, port=None):
    request_id = journal.claim(settings.camera_id, trigger_id)
    if request_id is None:
        LOG.warning("Bỏ qua trigger đã nhận; không chụp lại hoặc gửi lại lệnh servo.")
        return None
    fruit_id = "F-" + request_id
    deadline = time.monotonic() + settings.job_timeout
    LOG.info("Bắt đầu quả %s, camera %s, trigger %s", fruit_id, settings.camera_id, trigger_id or "legacy")
    try:
        image = camera.capture(deadline)
        label = cloud.classify(image, fruit_id, request_id, deadline)
        if time.monotonic() >= deadline or label not in LABELS:
            raise BridgeError("Không có kết quả hợp lệ trong thời gian cho phép.")
    except BridgeError as error:
        LOG.warning("%s: %s Chọn nhánh lỗi REJECT.", fruit_id, error)
        label = "REJECT"
    command = f"SORT:{label}\n".encode("ascii")
    if port is not None:
        # Failed/partial writes are ambiguous: never reconnect or resend automatically.
        controller_write(port, command)
    journal.finish(request_id, label)
    LOG.info("%s -> %s%s", fruit_id, label, " (kiểm tra thủ công, không gửi Serial)" if port is None else "")
    return label


def controller_write(port, command):
    """A partial command is ambiguous; never reconnect or retry a motor command."""
    port._autosort_uncertain_write = True
    if port.write(command) != len(command):
        raise serial.SerialException("Incomplete controller write")
    port.flush()
    port._autosort_uncertain_write = False


def arm_controller(port, settings):
    if settings.job_timeout > CONTROLLER_MAX_JOB_SECONDS:
        raise BridgeError("JOB_TIMEOUT_SECONDS phải <=25 giây với firmware USB Serial (watchdog 30 giây).")
    session_id = uuid4().hex
    controller_write(port, f"BRIDGE:READY:{session_id}\n".encode("ascii"))
    return session_id


def wait_controller_started(port, session_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        line = port.read_until(b"\n", 128)
        if line in (f"CONTROLLER:RUNNING:{session_id}\n".encode("ascii"),
                    f"CONTROLLER:RUNNING:{session_id}\r\n".encode("ascii")): return
        if line.startswith(b"FAULT:"): raise BridgeError("Firmware từ chối chạy. Kiểm tra trạm rồi reset ESP32.")
    raise BridgeError("ESP32 chưa xác nhận chạy; cần firmware USB Serial mới.")


def stop_controller(port):
    if getattr(port, "_autosort_uncertain_write", False): return False
    controller_write(port, b"BRIDGE:STOP\n")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        line = port.read_until(b"\n", 128)
        if line in (b"FAULT:BRIDGE_STOP\n", b"FAULT:BRIDGE_STOP\r\n"): return True
        if line.startswith(b"FAULT:"): return False
    return False


def legacy_main():
    # Windows redirected output may default to cp1252; keep Vietnamese help/logs readable.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", action="store_true", help="Nhấn Enter để thử camera/cloud; không kết nối ESP32")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    port = journal = run = camera = None
    run_reason = "START_FAILED"
    serial_failed = controller_fault = False
    try:
        settings = Settings.from_environment(manual=args.manual)
        with requests.Session() as phone_session, requests.Session() as cloud_session:
            camera, cloud = create_camera(settings, phone_session), CloudAI(settings, cloud_session)
            cloud.check_ready()
            journal = EventJournal(settings.state_path)
            run = DeviceRun(settings, requests.Session(), manual=args.manual)
            run.start()
            if args.manual: run.keep_manual_alive()
            cloud.run_id = run.id
            if not args.manual:
                port = serial.Serial(settings.serial_port, settings.baud_rate, timeout=1, write_timeout=2)
                time.sleep(2)
                session_id = arm_controller(port, settings)
                wait_controller_started(port, session_id)
                LOG.info("Đã kết nối ESP32 controller; chỉ nhận từng quả một.")
            run_reason = "BRIDGE_ERROR"
            last_ping = 0.0
            while True:
                run.heartbeat()
                if args.manual:
                    input("Nhấn Enter để lấy ảnh từ nguồn camera đã chọn (Ctrl+C để dừng): ")
                    run.heartbeat()
                    trigger_id = None
                else:
                    if time.monotonic() - last_ping >= 1.0:
                        controller_write(port, b"BRIDGE:PING\n")
                        last_ping = time.monotonic()
                    raw = port.read_until(b"\n", 128)
                    if not raw:
                        continue
                    if not raw.endswith(b"\n"):
                        raise BridgeError("Serial trả dòng không hoàn chỉnh/quá dài. Dừng bridge để kiểm tra firmware.")
                    line = raw.decode("ascii", errors="replace").strip()
                    if line.startswith("FAULT:"):
                        controller_fault = True
                        raise BridgeError("Firmware đã khóa trạm. Kiểm tra phần cứng/quả đang dở, reset ESP32 rồi chạy lại bridge.")
                    trigger_id = parse_trigger(line)
                    if trigger_id == "":
                        continue
                    if trigger_id is None:
                        LOG.warning("TRIGGER chưa có ID: không phân biệt được trigger lặp. Firmware nên gửi TRIGGER:<boot-id>:<counter>.")
                process_trigger(trigger_id, settings, camera, cloud, journal, port)
    except (KeyboardInterrupt, EOFError):
        run_reason = "NORMAL_STOP"
        LOG.info("Đã dừng bridge. Firmware phải có watchdog để xử lý lượt đang chờ.")
    except (serial.SerialException, OSError, sqlite3.Error):
        serial_failed = True
        run_reason = "SERIAL_ERROR"
        LOG.error("Lỗi Serial hoặc nhật ký cục bộ. Dừng bridge; không tự kết nối/gửi lại lệnh. Kiểm tra trạm trước khi chạy lại.")
        return 1
    except BridgeError as error:
        LOG.error("%s", error)
        return 1
    finally:
        if camera is not None:
            camera.close()
        if port is not None:
            if controller_fault:
                run_reason = "CONTROLLER_FAULT"
            elif not serial_failed:
                try:
                    if not stop_controller(port): run_reason = "STOP_UNCONFIRMED"
                except (serial.SerialException, OSError): run_reason = "SERIAL_ERROR"
            port.close()
        if journal is not None:
            journal.close()
        if run is not None:
            try: run.stop(run_reason)
            except BridgeError:
                LOG.warning("Chưa xác nhận đóng phiên trên cloud; phiên sẽ hết hạn khi mất heartbeat (90 giây).")
            finally: run.session.close()
    return 0


def main():
    if '--manual' in sys.argv: return legacy_main()
    load_dotenv(Path(__file__).with_name('.env'))
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    from web_control import web_main
    try: return web_main(Settings.from_environment())
    except BridgeError as error:
        LOG.error('%s', error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
