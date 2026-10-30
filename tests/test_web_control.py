"""Commands, ACKs and late inference with a single mocked Serial owner."""
from concurrent.futures import Future
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'camera-bridge'))
import bridge
from web_control import WebAgent

class WebControlTests(unittest.TestCase):
    def setUp(self):
        self.port=Mock(); self.port.write.side_effect=len
        self.journal=Mock()
        self.settings=bridge.Settings(phone_url='http://127.0.0.1/shot.jpg',api_key='k'*40)
        self.agent=WebAgent(self.settings,self.port,Mock(),self.journal)
        self.agent.api=Mock(return_value={})
        self.addCleanup(lambda:self.agent.pool.shutdown(wait=False,cancel_futures=True))
        self.run=str(uuid4())
    def command(self,action):
        return {'id':str(uuid4()),'runId':self.run,'action':action,'expiresInSeconds':15,'status':'DELIVERED'}
    def active(self):
        self.agent.run=Mock(id=self.run)
    def test_connect_is_standby_and_never_starts_a_run(self):
        self.port.read_until.return_value=b'CONTROLLER:IDLE\n'
        self.agent.connect()
        self.assertIsNone(self.agent.run)
        self.port.write.assert_called_once_with(b'BRIDGE:CONNECT\n')
        self.agent.api.assert_called_once_with('register',{'cameraId':self.settings.camera_id})
    def test_default_entrypoint_uses_web_standby(self):
        with patch.object(sys,'argv',['bridge.py']),patch.object(bridge.Settings,'from_environment',return_value=self.settings),patch('web_control.web_main',return_value=0) as run:
            self.assertEqual(bridge.main(),0)
        run.assert_called_once_with(self.settings)
    def test_start_creates_cloud_session_before_serial_and_duplicate_does_not_replay(self):
        cmd=self.command('START');events=[]
        self.agent.api.return_value={'command':cmd}
        self.port.write.side_effect=lambda data: (events.append('serial') if data.startswith(b'CONTROL:') else None) or len(data)
        with patch('web_control.DeviceRun') as client,patch('web_control.time.monotonic',return_value=1):
            client.return_value.start.side_effect=lambda:events.append('cloud')
            self.agent.handle_command(cmd,1)
            self.agent.handle_command(cmd,1)
        self.assertEqual(events,['cloud','serial'])
        self.assertIn(b':START:',self.port.write.call_args.args[0])
        with patch('web_control.time.monotonic',return_value=2):
            self.agent.handle_line(f'ACK:{UUID(cmd["id"]).hex}:RUNNING\n'.encode())
        self.assertEqual(self.agent.state,'RUNNING')
        self.assertIsNone(self.agent.pending)
    def test_pause_polled_while_inference_is_busy_and_paused_result_is_scoped(self):
        self.active();cmd=self.command('PAUSE');future=Future()
        self.agent.future=(future,self.run,'1','request')
        self.port.read_until.return_value=b''
        self.agent.api.return_value={'command':cmd}
        with patch('web_control.time.monotonic',return_value=10):self.agent.step()
        self.assertIn(b':PAUSE:',self.port.write.call_args.args[0])
        with patch('web_control.time.monotonic',return_value=11):
            self.agent.handle_line(f'ACK:{UUID(cmd["id"]).hex}:PAUSED\n'.encode())
        future.set_result('RIPE');self.agent.finish_inference()
        self.assertEqual(self.port.write.call_args.args[0],f'RESULT:{UUID(self.run).hex}:1:RIPE\n'.encode())
        self.assertEqual(self.agent.state,'PAUSED')
    def test_stop_discards_late_results_and_new_run_cannot_receive_old_result(self):
        self.active();cmd=self.command('STOP');future=Future()
        self.agent.future=(future,self.run,'1','request')
        with patch('web_control.time.monotonic',return_value=1):
            self.agent.handle_command(cmd,1)
            self.agent.handle_line(f'ACK:{UUID(cmd["id"]).hex}:IDLE\n'.encode())
        self.assertIsNone(self.agent.run);self.assertIsNone(self.agent.future)
        self.port.write.reset_mock()
        old=Future();old.set_result('GREEN');self.agent.future=(old,self.run,'1','old-request')
        self.agent.run=Mock(id=str(uuid4()))
        self.agent.finish_inference();self.port.write.assert_not_called()
    def test_expired_and_wrong_run_commands_never_write_serial(self):
        self.active();cmd=self.command('PAUSE');cmd['runId']=str(uuid4())
        with self.assertRaises(bridge.BridgeError):self.agent.handle_command(cmd,0)
        self.port.write.assert_not_called()
        cmd=self.command('START');cmd['expiresInSeconds']=-1
        with self.assertRaises(bridge.BridgeError):self.agent.handle_command(cmd,0)
        self.port.write.assert_not_called()
    def test_partial_serial_write_is_not_retried(self):
        self.active();self.port.write.return_value=3;self.port.write.side_effect=None
        with patch('web_control.time.monotonic',return_value=1):
            with self.assertRaises(bridge.serial.SerialException):self.agent.handle_command(self.command('PAUSE'),1)
        self.assertTrue(self.port._autosort_uncertain_write)
        self.assertFalse(bridge.stop_controller(self.port))
        self.port.write.assert_called_once()
    def test_stop_queued_during_startup_prevents_motor_start(self):
        start=self.command('START');stop=self.command('STOP')
        self.agent.api.return_value={'command':stop}
        with patch('web_control.DeviceRun'),patch('web_control.time.monotonic',return_value=1):
            self.agent.handle_command(start,1)
        frames=[call.args[0] for call in self.port.write.call_args_list if call.args[0].startswith(b'CONTROL:')]
        self.assertEqual(len(frames),1);self.assertIn(b':STOP:',frames[0])

if __name__=='__main__':unittest.main()
