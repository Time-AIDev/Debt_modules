"""Native uploads must wait for a complete bounded scanner verdict, fail closed."""
import struct

import pytest

from app.attachments import scanner


class Socket:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.timeout = None
        self.sent = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def settimeout(self, seconds): self.timeout = seconds
    def sendall(self, raw): self.sent.append(raw)
    def recv(self, size):
        value = next(self.replies, b'')
        if callable(value): value = value(self.timeout)
        return value


def configure(monkeypatch, replies):
    sock = Socket(replies)
    monkeypatch.setattr(scanner, '_env', lambda key, default=None: {'CLAMAV_HOST': 'scanner'}.get(key, default))
    def connect(address, timeout):
        assert address == ('scanner', 3310) and timeout == 10
        return sock
    monkeypatch.setattr(scanner.socket, 'create_connection', connect)
    return sock


def test_archive_verdict_after_ten_seconds_is_received_without_skipping_scanning(monkeypatch):
    def delayed(timeout):
        assert 10 < timeout <= 240
        return b'stream: OK\0'
    sock = configure(monkeypatch, [delayed])
    raw = b'x' * (scanner.CHUNK + 7)
    assert scanner.scan(raw)['state'] == 'CLEAN'
    assert sock.sent == [b'zINSTREAM\0', struct.pack('>I', scanner.CHUNK) + raw[:scanner.CHUNK],
                         struct.pack('>I', 7) + raw[scanner.CHUNK:], struct.pack('>I', 0)]


def test_partial_replies_share_one_deadline_instead_of_extending_it(monkeypatch):
    ticks = iter([0, 1, 2, 200, 241])
    monkeypatch.setattr(scanner.time, 'monotonic', lambda: next(ticks))
    sock = configure(monkeypatch, [b'stream: ', b'OK\0'])
    with pytest.raises(scanner.ScannerUnavailable, match='TimeoutError'):
        scanner.scan(b'file')
    assert sock.timeout == 40


@pytest.mark.parametrize('reply', [b'stream: OK', b'stream: NOT OK\0', b'ERROR OK\0', b'x' * 4097, b''])
def test_incomplete_oversized_or_non_verdict_responses_are_not_clean(monkeypatch, reply):
    configure(monkeypatch, [reply])
    with pytest.raises(scanner.ScannerUnavailable): scanner.scan(b'file')


def test_completed_malware_verdict_remains_rejected(monkeypatch):
    configure(monkeypatch, [b'stream: EICAR FOUND\0'])
    with pytest.raises(scanner.Infected) as result: scanner.scan(b'file')
    assert result.value.signature == 'EICAR'
