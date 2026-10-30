"""Preview camera frames and optionally run local v1, without cloud or Serial."""
import argparse
from datetime import datetime
import html
import io
import json
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv
from PIL import Image
import requests

from bridge import BridgeError, Settings, create_camera

ROOT = Path(__file__).resolve().parents[1]


def make_sample(destination):
    """Three existing project images in a real MJPEG file; not a model benchmark."""
    import cv2
    import numpy as np
    if destination.suffix.lower() != '.avi' or destination.exists():
        raise BridgeError('Chọn file .avi mới để tạo video mẫu; không ghi đè file có sẵn.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*'MJPG'), 1, (640, 480))
    try:
        if not writer.isOpened():
            raise BridgeError('Không tạo được video mẫu MJPEG.')
        for name in ('quatsample.jpg', 'ripe.jpg', 'reject.jpg'):
            with Image.open(ROOT / 'cloud-ai' / name) as source:
                image = source.convert('RGB')
                image.thumbnail((640, 480))
                canvas = Image.new('RGB', (640, 480), (32, 32, 32))
                canvas.paste(image, ((640-image.width)//2, (480-image.height)//2))
                writer.write(cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def write_report(output, frames, source, error=None):
    report = {'source': source, 'cloud_contacted': False, 'serial_opened': False,
              'status': 'error' if error else 'ok', 'frames': frames}
    if error:
        report['error'] = error
    (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    cards = []
    for row in frames:
        result = row.get('prediction')
        text = (f"{result['label']} · {result['confidence']:.1%} · {result['inference_ms']} ms"
                if result else 'Ảnh xem trước — chưa chạy AI')
        cards.append(f'<article><img src="{row["file"]}" alt="Khung hình {row["number"]}">'
                     f'<h2>Khung hình {row["number"]}</h2><p>{html.escape(text)}</p></article>')
    notice = f'<p role="alert">{html.escape(error)}</p>' if error else ''
    page = '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
    page += '<title>AutoSort — Kiểm tra camera</title><style>body{font:16px system-ui;background:#f3f7f5;color:#173d33;max-width:1200px;margin:32px auto;padding:0 20px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}article{background:white;padding:16px;border-radius:12px}img{width:100%;aspect-ratio:4/3;object-fit:contain;background:#e8eeea}h2{font-size:18px}</style>'
    page += '<h1>Kiểm tra camera AutoSort</h1><p>Chạy trên laptop. Không gửi cloud, không tạo phiên, không điều khiển ESP32.</p>'
    page += notice + '<main>' + ''.join(cards) + '</main></html>'
    (output / 'index.html').write_text(page, encoding='utf-8')


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['phone', 'webcam', 'video'])
    parser.add_argument('--index', type=int, help='Camera index: thử lần lượt 0, 1, 2 và xác nhận đúng ảnh DroidCam')
    parser.add_argument('--backend', choices=['auto', 'dshow', 'msmf'])
    parser.add_argument('--video-file', type=Path)
    parser.add_argument('--frames', type=int, default=1)
    parser.add_argument('--interval', type=float, default=.1)
    parser.add_argument('--infer-local', action='store_true', help='Chạy model v1 trên laptop, không gọi cloud')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--make-sample', type=Path, help='Tạo video .avi ba khung từ ảnh mẫu của dự án rồi thoát')
    args = parser.parse_args(argv)
    if not 1 <= args.frames <= 300 or not 0 <= args.interval <= 10:
        parser.error('frames phải 1–300; interval phải 0–10 giây')
    load_dotenv(Path(__file__).with_name('.env'))
    for name, value in [('CAMERA_SOURCE', args.source), ('CAMERA_INDEX', args.index),
                        ('CAMERA_BACKEND', args.backend), ('CAMERA_VIDEO_PATH', args.video_file)]:
        if value is not None:
            os.environ[name] = str(value)
    camera = output = None
    owns_output = False
    frames = []
    try:
        if args.make_sample:
            make_sample(args.make_sample)
            print(f'Đã tạo video mẫu: {args.make_sample.resolve()} (3 khung; không phải kiểm thử độ chính xác).')
            return 0
        settings = Settings.from_environment(manual=True, camera_only=True)
        engine = None
        if args.infer_local:
            sys.path.insert(0, str(ROOT / 'cloud-ai'))
            from worker import Engine
            engine = Engine(ROOT / 'cloud-ai/model')
            if not engine.model_ready:
                raise BridgeError('Model v1 local chưa sẵn sàng; không dùng kết quả MOCK.')
        output = args.output or ROOT / '.local' / ('camera-check-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        output.mkdir(parents=True, exist_ok=False)
        owns_output = True
        with requests.Session() as session:
            camera = create_camera(settings, session)
            for number in range(1, args.frames + 1):
                image = camera.capture(time.monotonic() + settings.capture_timeout)
                filename = f'frame-{number:03d}.jpg'
                (output / filename).write_bytes(image)
                with Image.open(io.BytesIO(image)) as decoded:
                    row = {'number': number, 'file': filename, 'width': decoded.width, 'height': decoded.height}
                if engine is not None:
                    row['prediction'] = engine.classify(f'preview-{number}', 'local-only', image)
                frames.append(row)
                if number < args.frames:
                    time.sleep(args.interval)
        write_report(output, frames, settings.camera_source)
        print(f'Đã lưu {len(frames)} ảnh. Mở: {(output / "index.html").resolve()}')
        return 0
    except (BridgeError, OSError, ValueError) as error:
        # BridgeError texts are operator-safe; other exceptions may expose private config.
        message = str(error) if isinstance(error, BridgeError) else 'Không đọc/ghi được ảnh, video hoặc thư mục kết quả.'
        if owns_output:
            write_report(output, frames, args.source or 'configured', message)
        print(message, file=sys.stderr)
        return 1
    finally:
        if camera is not None:
            camera.close()


if __name__ == '__main__':
    raise SystemExit(main())
