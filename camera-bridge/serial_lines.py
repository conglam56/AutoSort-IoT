"""Assemble bounded controller lines across pySerial read timeouts."""
from time import monotonic

from bridge_errors import BridgeError


class SerialLineReader:
    MAX_BYTES = 128
    PARTIAL_TIMEOUT = 1.0

    def __init__(self):
        self._buffer = bytearray()
        self._since = None

    @property
    def has_partial(self):
        return bool(self._buffer)

    def _check_deadline(self):
        if self._since is not None and monotonic() - self._since >= self.PARTIAL_TIMEOUT:
            raise BridgeError('Dòng Serial chưa hoàn chỉnh sau 1 giây; kiểm tra USB/baud rate và reset trạm.')

    def read(self, port):
        self._check_deadline()
        chunk = port.read_until(b'\n', self.MAX_BYTES - len(self._buffer))
        self._check_deadline()
        if not chunk:
            return b''
        if not isinstance(chunk, bytes) or len(self._buffer) + len(chunk) > self.MAX_BYTES:
            raise BridgeError('Dòng Serial vượt giới hạn; kiểm tra firmware và đường truyền.')
        if not self._buffer and not chunk.endswith(b'\n'):
            self._since = monotonic()
        self._buffer.extend(chunk)
        if self._buffer.endswith(b'\n'):
            line = bytes(self._buffer)
            self._buffer.clear()
            self._since = None
            return line
        if len(self._buffer) >= self.MAX_BYTES:
            raise BridgeError('Dòng Serial vượt giới hạn; kiểm tra firmware và đường truyền.')
        return b''


def reader_for(port):
    reader = getattr(port, '_autosort_line_reader', None)
    if not isinstance(reader, SerialLineReader):
        reader = SerialLineReader()
        port._autosort_line_reader = reader
    return reader


def read_controller_line(port):
    return reader_for(port).read(port)


def controller_line_pending(port):
    return reader_for(port).has_partial
