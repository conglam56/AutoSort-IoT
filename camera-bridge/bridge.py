"""Phone JPEG -> Cloud AI -> USB Serial ESP32 controller (not ESP32-CAM)."""
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
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
import requests
import serial

LOG = logging.getLogger("autosort-bridge")
LABELS = frozenset({"GREEN", "RIPE", "REJECT"})
MAX_IMAGE_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 16_384
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


class BridgeError(RuntimeError):
    """Operator-safe message; never contains URLs, headers or credentials."""


@dataclass(frozen=True)
class Settings:
    phone_url: str
    api_key: str
    serial_port: str = ""
    cloud_url: str = "https://autosort-iot.onrender.com/infer"
    camera_id: str = "phone_cam01"
    baud_rate: int = 115200
    capture_timeout: float = 5.0
    request_timeout: float = 5.0
    job_timeout: float = 20.0
    startup_timeout: float = 90.0
    attempts: int = 3
    state_path: Path = Path(__file__).parent / ".local" / "bridge-state.sqlite3"

    @classmethod
    def from_environment(cls, manual=False):
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
            )
        except ValueError as error:
            raise BridgeError("Cấu hình số không hợp lệ trong camera-bridge/.env.") from error
        for name, value in (("phone", settings.phone_url), ("cloud", settings.cloud_url)):
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
        if (not settings.api_key or len(settings.api_key) < 32 or settings.api_key.startswith("replace_")
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", settings.camera_id)):
            raise BridgeError("Cần DEVICE_API_KEY riêng tối thiểu 32 ký tự và CAMERA_ID hợp lệ.")
        if not manual and not settings.serial_port:
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


class CloudAI:
    def __init__(self, settings, session):
        self.settings, self.session = settings, session

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
                    headers={"X-API-Key": self.settings.api_key, "Idempotency-Key": request_id},
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
                or result.get("request_id") != request_id or not isinstance(label, str) or label not in LABELS or not valid_confidence
                or not isinstance(result.get("model_version"), str) or not result["model_version"]
                or result["model_version"].lower().startswith("mock")
                or not isinstance(reason, str) or reason not in {"CLASSIFIED", "LOW_CONFIDENCE"}
                or (reason == "LOW_CONFIDENCE" and label != "REJECT")
                or (reason == "CLASSIFIED" and result.get("raw_label") != label)):
            raise BridgeError("Kết quả cloud sai mã quả, MOCK hoặc không hợp lệ; không dùng nhãn này để điều khiển.")
        return label


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
        if port.write(command) != len(command):
            raise serial.SerialException("Incomplete controller write")
        port.flush()
    journal.finish(request_id, label)
    LOG.info("%s -> %s%s", fruit_id, label, " (kiểm tra thủ công, không gửi Serial)" if port is None else "")
    return label


def main():
    # Windows redirected output may default to cp1252; keep Vietnamese help/logs readable.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", action="store_true", help="Nhấn Enter để thử camera/cloud; không kết nối ESP32")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    port = journal = None
    try:
        settings = Settings.from_environment(manual=args.manual)
        with requests.Session() as phone_session, requests.Session() as cloud_session:
            camera, cloud = PhoneCamera(settings, phone_session), CloudAI(settings, cloud_session)
            cloud.check_ready()
            journal = EventJournal(settings.state_path)
            if not args.manual:
                port = serial.Serial(settings.serial_port, settings.baud_rate, timeout=1, write_timeout=2)
                time.sleep(2)
                LOG.info("Đã kết nối ESP32 controller; chỉ nhận từng quả một.")
            while True:
                if args.manual:
                    input("Nhấn Enter để chụp ảnh từ điện thoại (Ctrl+C để dừng): ")
                    trigger_id = None
                else:
                    raw = port.read_until(b"\n", 128)
                    if not raw:
                        continue
                    if not raw.endswith(b"\n"):
                        raise BridgeError("Serial trả dòng không hoàn chỉnh/quá dài. Dừng bridge để kiểm tra firmware.")
                    trigger_id = parse_trigger(raw.decode("ascii", errors="replace").strip())
                    if trigger_id == "":
                        continue
                    if trigger_id is None:
                        LOG.warning("TRIGGER chưa có ID: không phân biệt được trigger lặp. Firmware nên gửi TRIGGER:<boot-id>:<counter>.")
                process_trigger(trigger_id, settings, camera, cloud, journal, port)
    except (KeyboardInterrupt, EOFError):
        LOG.info("Đã dừng bridge. Firmware phải có watchdog để xử lý lượt đang chờ.")
    except (serial.SerialException, OSError, sqlite3.Error):
        LOG.error("Lỗi Serial hoặc nhật ký cục bộ. Dừng bridge; không tự kết nối/gửi lại lệnh. Kiểm tra trạm trước khi chạy lại.")
        return 1
    except BridgeError as error:
        LOG.error("%s", error)
        return 1
    finally:
        if port is not None:
            port.close()
        if journal is not None:
            journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
