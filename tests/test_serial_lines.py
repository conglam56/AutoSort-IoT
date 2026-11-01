"""Realistic partial serial reads: no action before newline, bounded failure modes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera-bridge'))
from serial_lines import SerialLineReader, read_controller_line, controller_line_pending
from bridge_errors import BridgeError


class SerialLineTests(unittest.TestCase):
    def test_crlf_split_across_timeouts_is_preserved_and_next_line_starts_fresh(self):
        port=Mock();port.read_until.side_effect=[b'STA',b'TE:1\r',b'',b'\n',b'COUNTS:G=1,R=0,X=0\n']
        for _ in range(3):self.assertEqual(read_controller_line(port),b'')
        self.assertTrue(controller_line_pending(port))
        self.assertEqual(read_controller_line(port),b'STATE:1\r\n')
        self.assertFalse(controller_line_pending(port))
        self.assertEqual(read_controller_line(port),b'COUNTS:G=1,R=0,X=0\n')

    def test_partial_line_deadline_is_not_extended_by_trickle_bytes(self):
        port=Mock();port.read_until.side_effect=[b'STA',b'T',b'E:1\n']
        with patch('serial_lines.monotonic',return_value=0) as clock:
            self.assertEqual(read_controller_line(port),b'')
            clock.return_value=.9;self.assertEqual(read_controller_line(port),b'')
            clock.return_value=1.01
            with self.assertRaisesRegex(BridgeError,'1 giây'):read_controller_line(port)
        self.assertEqual(port.read_until.call_count,2)

    def test_partial_line_exceeding_byte_limit_fails(self):
        port=Mock();port.read_until.side_effect=[b'X'*100,b'Y'*28]
        self.assertEqual(read_controller_line(port),b'')
        with self.assertRaisesRegex(BridgeError,'vượt giới hạn'):read_controller_line(port)

    def test_full_length_complete_line_is_accepted(self):
        port=Mock();port.read_until.return_value=b'X'*127+b'\n'
        self.assertEqual(read_controller_line(port),b'X'*127+b'\n')

    def test_silence_does_not_start_partial_deadline(self):
        port=Mock();port.read_until.side_effect=[b'',b'',b'STATE:1\n']
        with patch('serial_lines.monotonic',side_effect=AssertionError('No partial deadline expected')):
            self.assertEqual(read_controller_line(port),b'')
            self.assertEqual(read_controller_line(port),b'')
            self.assertEqual(read_controller_line(port),b'STATE:1\n')

    def test_timeout_during_continuation_read_does_not_accept_late_newline(self):
        port=Mock();port.read_until.side_effect=[b'STA',b'TE:1\n']
        with patch('serial_lines.monotonic',side_effect=[0,.9,1.1]):
            self.assertEqual(read_controller_line(port),b'')
            with self.assertRaisesRegex(BridgeError,'1 giây'):read_controller_line(port)


if __name__=='__main__':unittest.main()
