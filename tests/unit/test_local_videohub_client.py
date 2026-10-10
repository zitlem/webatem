"""Local addition: atem_control.videohub.client.Hub, the videohubwire
extension (locks, multi-crosspoint routing, take mode)."""
import socket

import pytest

from atem_control.videohub.client import Hub
from videohubwire import VideohubError

PREAMBLE = (b"PROTOCOL PREAMBLE:\nVersion: 2.8\n\n"
            b"VIDEOHUB DEVICE:\nDevice present: true\nModel name: Blackmagic Smart Videohub 20 x 20\n"
            b"Friendly name: Test Hub\nUnique ID: 7C2E0D0B1321\nVideo inputs: 4\nVideo outputs: 4\n\n"
            b"INPUT LABELS:\n0 CAM 1\n1 CAM 2\n2 CAM 3\n3 CAM 4\n\nOUTPUT LABELS:\n0 PGM\n1 AUX\n2 REC\n3 MON\n\n"
            b"VIDEO OUTPUT LOCKS:\n0 U\n1 U\n2 L\n3 U\n\nVIDEO OUTPUT ROUTING:\n0 0\n1 1\n2 2\n3 3\n\n"
            b"CONFIGURATION:\nTake Mode: true\n\nTAKE MODE:\n0 false\n1 true\n2 false\n3 false\n\nEND PRELUDE:\n\n")


class FakeHub:
    def __init__(self, replies=()):
        self.script, self.replies, self.sent = [PREAMBLE], list(replies), b''

    def settimeout(self, _t):
        pass

    def sendall(self, data):
        self.sent += data
        for prefix, answer in self.replies:
            if data.startswith(prefix):
                self.script.append(answer)
                return

    def recv(self, _n):
        if not self.script:
            raise socket.timeout()
        return self.script.pop(0)

    def shutdown(self, _how):
        pass

    def close(self):
        pass


def hub(replies=()):
    fake = FakeHub(replies)
    h = Hub('192.0.2.5', socket_factory=lambda addr, timeout: fake, read_timeout=0.2)
    h.connect()
    return h, fake


def test_take_mode_and_unique_id_in_state():
    h, _ = hub()
    s = h.state()
    assert s['device']['unique_id'] == '7C2E0D0B1321'
    assert s['device']['take_mode'] is True
    assert [o['take_mode'] for o in s['outputs']] == [False, True, False, False]


def test_route_many_is_one_block():
    h, fake = hub([(b'VIDEO OUTPUT ROUTING:', b'ACK\n\n')])
    h.route_many([(0, 3), (1, 2)])
    assert fake.sent.endswith(b'VIDEO OUTPUT ROUTING:\n0 3\n1 2\n\n')
    assert h.routing[0] == 3 and h.routing[1] == 2


def test_route_many_rejects_out_of_range():
    h, fake = hub()
    with pytest.raises(VideohubError):
        h.route_many([(0, 9)])
    assert b'VIDEO OUTPUT ROUTING' not in fake.sent


@pytest.mark.parametrize('mode, code, after', [('lock', 'O', 'O'), ('unlock', 'U', 'U'), ('force', 'F', 'U')])
def test_set_lock(mode, code, after):
    h, fake = hub([(b'VIDEO OUTPUT LOCKS:', b'ACK\n\n')])
    h.set_lock(2, mode)
    assert fake.sent.endswith(f'VIDEO OUTPUT LOCKS:\n2 {code}\n\n'.encode())
    assert h.locks[2] == after


def test_nak_raises():
    h, _ = hub([(b'VIDEO OUTPUT LOCKS:', b'NAK\n\n')])
    with pytest.raises(VideohubError, match='refused'):
        h.set_lock(0, 'lock')
