"""Real HTTP/Java/ONNX/PostgreSQL with an explicit Serial hardware fixture."""
from collections import deque
import time
from uuid import uuid4,UUID
import requests
import bridge
from web_control import WebAgent


def run_web_e2e(client,settings,folder,capture_gate):
    class SerialFixture:
        def __init__(self): self.lines=deque();self.writes=[];self.state='IDLE'
        def write(self,data):
            self.writes.append(data)
            line=data.decode().strip()
            if line=='BRIDGE:CONNECT':self.lines.append(b'CONTROLLER:IDLE\r\n')
            elif line=='BRIDGE:STOP':self.state='FAULT';self.lines.append(b'FAULT:BRIDGE_STOP\r\n')
            elif line.startswith('CONTROL:'):
                _,id,action,run=line.split(':')
                self.state={'START':'RUNNING','RESUME':'RUNNING','PAUSE':'PAUSED','STOP':'IDLE'}[action]
                self.lines.append(f'ACK:{id}:{self.state}\r\n'.encode())
            return len(data)
        def flush(self):pass
        def read_until(self,terminator=b'\n',size=128):
            if not self.lines:return b''
            line=self.lines.popleft();length=min(7,size,len(line))
            if length<len(line):self.lines.appendleft(line[length:])
            return line[:length]  # USB read timeouts may split a single firmware line.
    port=SerialFixture()
    with requests.Session() as http,bridge.EventJournal(folder/'web-bridge.sqlite3') as journal:
        agent=WebAgent(settings,port,http,journal)
        if settings.camera_source == 'video':
            # Keep inference in flight until PAUSE is ACKed, then decode a real video.
            # This explicit fixture never opens a real COM port or production service.
            capture = agent.local_camera.capture
            def gated_capture(deadline):
                if not capture_gate.wait(timeout=10):
                    raise bridge.BridgeError('Video fixture gate timed out')
                return capture(deadline)
            agent.local_camera.capture = gated_capture
        try:
            agent.connect();assert port.state=='IDLE' and agent.run is None
            assert client.get('/api/session/current').json() is None
            def command(action):
                state=client.get('/api/station').json()
                response=client.post('/api/station/commands',json={'action':action,'revision':state['revision']},headers={'Idempotency-Key':uuid4().hex})
                response.raise_for_status();return response.json()
            def pump(predicate):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    agent.step()
                    if predicate():return
                    time.sleep(.02)
                raise AssertionError('Web control E2E timeout')
            start=command('START');pump(lambda:agent.pending is None and agent.state=='RUNNING')
            session=client.get('/api/session/current').json();assert session and session['automatic']
            port.lines.append(f'TRIGGER:{UUID(start["runId"]).hex}:1\n'.encode())
            pump(lambda:agent.future is not None)
            command('PAUSE');pump(lambda:agent.pending is None and agent.state=='PAUSED')
            assert port.state=='PAUSED'
            assert client.get('/api/session/current').json()['id']==session['id']
            capture_gate.set()
            pump(lambda:any(w.startswith(b'RESULT:') for w in port.writes))
            assert port.state=='PAUSED'  # AI completion itself cannot resume the conveyor.
            result=[w for w in port.writes if w.startswith(b'RESULT:')]
            assert result==[f'RESULT:{UUID(start["runId"]).hex}:1:GREEN\n'.encode()]
            assert len(client.get('/api/session/current').json()['fruits'])==1
            command('RESUME');pump(lambda:agent.pending is None and agent.state=='RUNNING')
            command('STOP');pump(lambda:agent.pending is None and agent.state=='IDLE')
            assert client.get('/api/session/current').json() is None
            saved=client.get('/api/sessions/'+session['id']).json()
            assert saved['endReason']=='NORMAL_STOP' and len(saved['fruits'])==1
            actions=[w.decode().split(':')[2] for w in port.writes if w.startswith(b'CONTROL:')]
            assert actions==['START','PAUSE','RESUME','STOP']
            if settings.camera_source == 'video':
                print('E2E VIDEO OK: real MJPEG decode -> JPEG -> localhost Java/ORT/PostgreSQL -> scoped Serial fixture result.',flush=True)
            print('E2E WEB OK: authenticated START -> real session -> paused camera/AI job -> scoped GREEN result while PAUSED -> RESUME -> STOP closes session; one Serial command per action.',flush=True)
        finally:
            capture_gate.set();agent.close()
