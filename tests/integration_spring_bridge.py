"""Run the packaged Java app + real ONNX worker + real bridge against localhost PG.

The camera and Serial are test fixtures. Production accounts/data are never used.
"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
import psycopg
from psycopg import sql
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "camera-bridge"))
import bridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=['classify', 'detect'], default='classify')
    parser.add_argument('--automatic', action='store_true')
    parser.add_argument('--web-control', action='store_true')
    parser.add_argument('--video-camera', action='store_true', help='Real local video decoder with the Serial fixture')
    args = parser.parse_args()
    if args.video_camera and not args.web_control:
        parser.error('--video-camera requires --web-control')
    url = os.environ["AUTOSORT_TEST_DATABASE_URL"]
    assert urlsplit(url).hostname in {"localhost", "127.0.0.1"}, "Integration test requires localhost PostgreSQL"
    schema = "autosort_e2e_" + uuid4().hex
    with psycopg.connect(url, connect_timeout=5) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    process = phone = None
    try:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            # Small fixed-output ONNX fixture: exercises ORT, not trained model accuracy.
            size = 320 if args.task == 'detect' else 224
            values = np.array([[[160], [160], [200], [200], [.95], [.03], [.02]]], dtype=np.float32) if args.task == 'detect' else np.array([[.95, .03, .02]], dtype=np.float32)
            graph = helper.make_graph([helper.make_node("Constant", [], ["probabilities"], value=numpy_helper.from_array(values))],
                "integration-only", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, size, size])],
                [helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, list(values.shape))])
            model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)
            onnx.save(model, folder / "best.onnx")
            metadata = {"classes": ["GREEN", "RIPE", "REJECT"] if args.task == 'detect' else ["GREEN", "REJECT", "RIPE"], "imgsz": size, "threshold": .7, "model_version": "integration-fixture", 'task': args.task}
            if args.task == 'detect':
                metadata['output_format'] = 'yolo11_raw'
                metadata.update(decision_policy='highest_confidence', threshold=0.0)
            (folder / "classes.json").write_text(json.dumps(metadata))
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            origin = f"http://127.0.0.1:{port}"
            password, key = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            env = {**os.environ, "DATABASE_URL": url, "DATABASE_SCHEMA": schema, "DATABASE_SSLMODE": "disable", "PORT": str(port),
                   "DEVICE_API_KEY": key, "COOKIE_SECURE": "false", "ALLOWED_ORIGINS": origin, "INITIALIZE_DATABASE": "true",
                   "BOOTSTRAP_ADMIN_PASSWORD": password, "PYTHON_BIN": sys.executable, "AI_MODEL_DIR": str(folder), "RENDER": "false"}
            with (folder / "java.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(["java", "-Xmx160m", "-XX:+UseSerialGC", "-jar", str(ROOT / "backend/target/autosort-backend-1.0.0.jar")],
                    cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=os.name != "nt")
                with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as client:
                    for _ in range(90):
                        if process.poll() is not None:
                            raise AssertionError("Java application exited before readiness")
                        try:
                            if client.get("/ready").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(1)
                    else:
                        raise AssertionError("Java application readiness timeout")
                    health = client.get("/health").json()
                    assert health["backend"] == "spring-boot" and health["mode"] == "onnx"
                    assert client.get('/dashboard/index.html').status_code in (302,303,307)
                    for asset in ("login.html", "app.js", "admin.js", "style.css"):
                        assert client.get("/dashboard/" + asset).status_code == 200
                    login = client.post("/api/auth/login", json={"username": "admin", "password": password})
                    login.raise_for_status()
                    client.headers["X-CSRF-Token"] = login.json()["csrfToken"]
                    if not args.automatic and not args.web_control:
                        client.post("/api/sessions/new", headers={"Idempotency-Key": "e2e-start"}).raise_for_status()
                    image = (ROOT / "cloud-ai/quatsample.jpg").read_bytes()
                    capture_gate=threading.Event()
                    class Snapshot(BaseHTTPRequestHandler):
                        def do_GET(self):
                            if args.web_control: capture_gate.wait(timeout=15)
                            self.send_response(200)
                            self.send_header("Content-Type", "image/jpeg")
                            self.end_headers()
                            self.wfile.write(image)

                        def log_message(self, *args):
                            pass
                    phone = ThreadingHTTPServer(("127.0.0.1", 0), Snapshot)
                    threading.Thread(target=phone.serve_forever, daemon=True).start()
                    class LostResponse(requests.Session):
                        calls = 0

                        def post(self, *args, **kwargs):
                            result = super().post(*args, **kwargs)
                            self.calls += 1
                            if self.calls == 1:
                                result.content  # Server committed; simulate losing its successful response.
                                result.close()
                                raise requests.Timeout("test-only lost response")
                            return result
                    class SerialFixture:
                        writes = []

                        def write(self, command):
                            self.writes.append(command)
                            return len(command)

                        def flush(self):
                            pass
                    settings = bridge.Settings(phone_url=f"http://127.0.0.1:{phone.server_port}/shot.jpg", api_key=key, cloud_url=origin + "/infer")
                    if args.video_camera:
                        from camera_check import make_sample
                        video = folder / 'fixture.avi'
                        make_sample(video)
                        settings = replace(settings, camera_source='video', video_path=str(video), capture_timeout=5)
                    if args.web_control:
                        from web_control_e2e import run_web_e2e
                        run_web_e2e(client,settings,folder,capture_gate)
                        stop(process);process=None
                        return
                    with requests.Session() as phone_session, LostResponse() as cloud_session, bridge.EventJournal(folder / "bridge.sqlite3") as journal:
                        cloud = bridge.CloudAI(settings, cloud_session)
                        cloud.check_ready()
                        run_session = requests.Session()
                        run = bridge.DeviceRun(settings, run_session) if args.automatic else None
                        if run:
                            run.start()
                            cloud.run_id = run.id
                        serial = SerialFixture()
                        result = bridge.process_trigger("boot-e2e:1", settings, bridge.PhoneCamera(settings, phone_session), cloud, journal, serial)
                        assert result == "GREEN" and serial.writes == [b"SORT:GREEN\n"] and cloud_session.calls == 2
                        assert bridge.process_trigger("boot-e2e:1", settings, bridge.PhoneCamera(settings, phone_session), cloud, journal, serial) is None
                    current = client.get("/api/session/current").json()
                    assert len(current["fruits"]) == 1 and current["fruits"][0]["label"] == "GREEN"
                    if run:
                        assert current['automatic'] is True
                        run.stop('NORMAL_STOP')
                        assert client.get('/api/session/current').json() is None
                        completed = client.get('/api/sessions/'+current['id']).json()
                        assert completed['status']=='COMPLETED' and completed['endReason']=='NORMAL_STOP'
                        again=bridge.DeviceRun(settings,run_session)
                        next_session=again.start()
                        assert next_session['sessionId']!=current['id']
                        again.stop('NORMAL_STOP')
                        run_session.close()
                        client.post('/api/auth/logout').raise_for_status()
                        print(f'E2E OK ({args.task}, automatic): device session -> phone JPEG -> bridge -> Spring Boot -> ORT -> PostgreSQL -> one Serial command; stop closes session; next start opens a distinct session.')
                        stop(process)
                        process=None
                        return
                    viewer_password = secrets.token_urlsafe(24)
                    client.post("/api/admin/users", json={"username": "operator", "password": viewer_password}).raise_for_status()
                    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=10) as viewer:
                        r = viewer.post("/api/auth/login", json={"username": "operator", "password": viewer_password})
                        r.raise_for_status()
                        viewer.headers["X-CSRF-Token"] = r.json()["csrfToken"]
                        assert viewer.post("/api/sessions/new").status_code == 409
                        ended = viewer.post("/api/sessions/" + current["id"] + "/end"); ended.raise_for_status()
                        assert viewer.post("/api/sessions/" + current["id"] + "/end").json()["endTime"] == ended.json()["endTime"]
                        assert viewer.post("/api/sessions/new").status_code == 200
                        assert viewer.get("/api/admin/users").status_code == 403
                    client.post("/api/auth/logout").raise_for_status()
                    print(f"E2E OK ({args.task}): phone JPEG -> bridge -> Spring Boot -> real ORT worker -> PostgreSQL -> one Serial command; operator operates; admin access blocked.")
            # Stop before closing temp model files (Windows locks native/model handles).
            stop(process)
            process = None
    finally:
        if process is not None:
            stop(process)
        if phone is not None:
            phone.shutdown()
            phone.server_close()
        with psycopg.connect(url, connect_timeout=5) as db:
            db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)


if __name__ == "__main__":
    main()
