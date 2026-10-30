"""Web-command agent; one Serial owner, inference isolated from control polling."""
from concurrent.futures import ThreadPoolExecutor
import logging
import re
import time
from uuid import UUID, uuid4

import requests
import serial

from bridge import (BridgeError, CloudAI, DeviceRun, EventJournal, PhoneCamera,
                    controller_write, parse_trigger, response_json, stop_controller)

LOG = logging.getLogger('autosort-bridge')

class DeviceConflict(BridgeError):
    def __init__(self,detail): super().__init__(detail);self.detail=detail


class WebAgent:
    def __init__(self, settings, port, http, journal):
        self.settings, self.port, self.http, self.journal = settings, port, http, journal
        self.id = str(uuid4())
        self.run = None
        self.pending = None
        self.future = None
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.last_poll = self.last_ping = 0.0
        self.state = 'IDLE'

    def api(self, action, body=None):
        base = self.settings.cloud_url.rsplit('/infer', 1)[0]
        with self.http.post(base + '/device/station/' + self.id + '/' + action,
                            json=body, headers={'X-API-Key': self.settings.api_key},
                            timeout=2, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                if response.status_code==409:
                    raise DeviceConflict(response_json(response).get('detail','DEVICE_CONFLICT'))
                raise BridgeError('Không xác nhận được kênh điều khiển web; dừng và kiểm tra trạm.')
            return response_json(response)

    def connect(self):
        controller_write(self.port, b'BRIDGE:CONNECT\n')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            line = self.port.read_until(b'\n', 128)
            if line == b'CONTROLLER:IDLE\n': break
            if line.startswith(b'FAULT:'): raise BridgeError('ESP32 đang khóa lỗi; kiểm tra và reset trạm.')
        else: raise BridgeError('Cần firmware điều khiển web mới; ESP32 chưa xác nhận chờ lệnh.')
        self.api('register', {'cameraId': self.settings.camera_id})
        LOG.info('Trạm đã kết nối, motor dừng. Đăng nhập web để Bắt đầu / Tạm dừng / Kết thúc.')

    def handle_command(self, command, polled_at):
        if command is None: return
        if self.pending is not None:
            if self.pending['id'] == command['id']: return
            if command.get('action')!='STOP' or command.get('runId')!=self.pending.get('runId'):
                raise BridgeError('Lệnh điều khiển thay đổi khi chưa xác nhận.')
            self.pending=None
        action = command.get('action')
        if action not in {'START', 'PAUSE', 'RESUME', 'STOP'}: raise BridgeError('Lệnh điều khiển không hợp lệ.')
        command_id, run_id = UUID(command['id']), UUID(command['runId'])
        remaining = float(command['expiresInSeconds'])
        if not 0 < remaining <= 15: raise BridgeError('Lệnh đã quá hạn; không áp dụng lệnh cũ.')
        deadline = polled_at + remaining
        if action == 'START':
            if self.run is not None: raise BridgeError('Trạm vẫn có lượt đang xử lý.')
            self.run = DeviceRun(self.settings, requests.Session())
            self.run.id = str(run_id)
            self.run.start()  # Database session exists before motor START.
            controller_write(self.port,b'BRIDGE:PING\n')
            checked_at=time.monotonic();latest=self.api('poll').get('command')
            if latest is None: raise BridgeError('Lệnh bắt đầu không còn hiệu lực.')
            if latest['id']!=command['id']:
                if latest.get('action')=='STOP' and latest.get('runId')==str(run_id):
                    self.handle_command(latest,checked_at);return
                raise BridgeError('Lệnh bắt đầu đã bị thay thế; không bật motor.')
        elif (self.run is None and action!='STOP') or (self.run is not None and self.run.id != str(run_id)):
            raise BridgeError('Lệnh thuộc lượt chạy khác; không điều khiển.')
        if time.monotonic() >= deadline: raise BridgeError('Lệnh đã quá hạn trước khi gửi ESP32.')
        self.pending = {**command, 'deadline': deadline, 'hex': command_id.hex}
        controller_write(self.port, f'CONTROL:{command_id.hex}:{action}:{run_id.hex}\n'.encode('ascii'))

    def handle_line(self, raw):
        if not raw: return
        if not raw.endswith(b'\n'): raise BridgeError('Dòng Serial chưa hoàn chỉnh; dừng trạm.')
        line = raw.decode('ascii', errors='strict').strip()
        if line.startswith('FAULT:'): raise BridgeError('Firmware đã khóa lỗi. Kiểm tra trạm tại chỗ rồi reset.')
        if line.startswith('ACK:'):
            _, id_hex, state = line.split(':', 2)
            if self.pending is None or id_hex != self.pending['hex']: return
            expected = {'START': 'RUNNING', 'RESUME': 'RUNNING', 'PAUSE': 'PAUSED', 'STOP': 'IDLE'}[self.pending['action']]
            if time.monotonic() >= self.pending['deadline']: raise BridgeError('ESP32 trả ACK quá hạn.')
            success = state == expected
            try:
                self.api('ack/' + self.pending['id'], {'state': expected if success else 'FAULT', 'success': success})
            except DeviceConflict as error:
                if error.detail=='COMMAND_EXPIRED':
                    polled_at=time.monotonic();new=self.api('poll').get('command')
                    if new and new.get('action')=='STOP' and new.get('runId')==self.pending.get('runId'):
                        self.pending=None;self.handle_command(new,polled_at);return
                raise
            action = self.pending['action']
            self.pending = None
            if not success: raise BridgeError('ESP32 từ chối lệnh; cần kiểm tra trạm.')
            self.state = state
            if action == 'STOP':
                if self.future is not None:
                    self.future[0].cancel()
                    self.future = None
                if self.run is not None: self.run.session.close()
                self.run = None
            return
        trigger = parse_trigger(line)
        if trigger in ('', None): return
        if self.pending and self.pending['action']=='STOP': return
        if self.run is None or not trigger.startswith(UUID(self.run.id).hex + ':'):
            raise BridgeError('Trigger không thuộc lượt đang chạy.')
        request_id = self.journal.claim(self.settings.camera_id, trigger)
        if request_id is None: return
        if self.future is not None: raise BridgeError('Có hơn một quả đang xử lý.')
        run_id = self.run.id
        counter = trigger.rsplit(':', 1)[1]
        if not re.fullmatch(r'[0-9]{1,10}', counter): raise BridgeError('Mã quả Serial không hợp lệ.')
        deadline = time.monotonic() + self.settings.job_timeout
        self.future = (self.pool.submit(self.infer, run_id, request_id, deadline), run_id, counter, request_id)

    def infer(self, run_id, request_id, deadline):
        with requests.Session() as phone_http, requests.Session() as cloud_http:
            camera, cloud = PhoneCamera(self.settings, phone_http), CloudAI(self.settings, cloud_http)
            cloud.run_id = run_id
            try:
                image = camera.capture(deadline)
                return cloud.classify(image, 'F-' + request_id, request_id, deadline)
            except BridgeError:
                LOG.warning('Chụp/AI thất bại; chỉ quả hiện tại dùng nhánh REJECT.')
                return 'REJECT'

    def finish_inference(self):
        if self.future is None or not self.future[0].done(): return
        future, run_id, counter, request_id = self.future
        self.future = None
        label = future.result()
        if self.run is None or self.run.id != run_id or (self.pending and self.pending['action'] == 'STOP'):
            return  # A late result must never reach a new run or restart a stopped belt.
        if label not in {'GREEN', 'RIPE', 'REJECT'}: raise BridgeError('AI trả nhãn không hợp lệ.')
        controller_write(self.port, f'RESULT:{UUID(run_id).hex}:{counter}:{label}\n'.encode('ascii'))
        self.journal.finish(request_id, label)

    def step(self):
        now = time.monotonic()
        if now - self.last_ping >= 1:
            controller_write(self.port, b'BRIDGE:PING\n')
            self.last_ping = now
        self.handle_line(self.port.read_until(b'\n', 128))
        if self.pending and time.monotonic() >= self.pending['deadline']:
            raise BridgeError('Không nhận được ACK đúng hạn; không gửi lại lệnh motor.')
        if now - self.last_poll >= .5:
            response = self.api('poll')
            self.last_poll = now
            self.handle_command(response.get('command'), now)
        self.finish_inference()

    def close(self):
        try: stop_controller(self.port)
        except (serial.SerialException, OSError, BridgeError): pass
        try: self.api('fault')
        except (requests.RequestException, BridgeError): pass
        if self.run is not None:
            try: self.run.stop('BRIDGE_ERROR')
            except BridgeError: pass
            self.run.session.close()
        self.pool.shutdown(wait=False, cancel_futures=True)


def web_main(settings):
    agent = None
    try:
        with requests.Session() as http:
            CloudAI(settings, http).check_ready()
            if settings.job_timeout > 25: raise BridgeError('JOB_TIMEOUT_SECONDS phải <=25 giây.')
            with EventJournal(settings.state_path) as journal, serial.Serial(settings.serial_port, settings.baud_rate,
                                                                           timeout=.1, write_timeout=2) as port:
                time.sleep(2)
                agent = WebAgent(settings, port, http, journal)
                try:
                    agent.connect()
                    while True: agent.step()
                finally: agent.close()
    except KeyboardInterrupt:
        LOG.info('Đã dừng bridge; trạm cần kết nối lại trước khi điều khiển web.')
        return 0
    except (BridgeError, requests.RequestException, serial.SerialException, OSError, ValueError) as error:
        LOG.error('Kênh điều khiển đã dừng (%s). Kiểm tra cloud/Serial và trạm rồi chạy lại bridge.', type(error).__name__)
        return 1
