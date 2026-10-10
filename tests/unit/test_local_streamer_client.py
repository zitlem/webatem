"""Local addition: the Streaming Encoder protocol client (atem_control.streamer.client)
against a scripted fake device. Protocol: Blackmagic Streaming Encoder Ethernet
Protocol v1.2."""
import socket

import pytest

from atem_control.streamer.client import Streamer, StreamerError, split_list

PREAMBLE = (
    b"PROTOCOL PREAMBLE:\nVersion: 1.2\n\n"
    b"IDENTITY:\nModel: Blackmagic Web Presenter 4K\nLabel: Web Presenter 4K\nUnique ID: 7C2E0D0B1999\n\n"
    b"NETWORK INTERFACE 0:\nName: Ethernet\nDynamic IP: true\nCurrent Addresses: 192.168.2.60/255.255.255.0\n\n"
    b"STREAM SETTINGS:\nVideo Mode: Auto\nCurrent Platform: YouTube RTMP\nCurrent Server: Primary\n"
    b"Current Quality Level: Streaming Medium\nStream Key: abc\nPassword:\n"
    b"Available Default Platforms: YouTube RTMP, YouTube SRT \\(Beta\\), Facebook\n"
    b"Available Servers: Primary, US West: Los Angeles\\, CA\n\n"
    b"STREAM STATE:\nStatus: Idle\nBitrate: 0\nDuration: 00:00:00:00\nCache Used: 0\n\n"
    b"END PRELUDE:\n\n")


class FakeDevice:
    """recv() hands out ``script`` chunk by chunk; ``replies`` maps the start
    of what the client sends to what the device answers."""

    def __init__(self, script, replies=()):
        self.script, self.replies, self.sent = list(script), list(replies), b''

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

    def close(self):
        pass


def connect(replies=(), split=True):
    chunks = [PREAMBLE[:90], PREAMBLE[90:]] if split else [PREAMBLE]
    fake = FakeDevice(chunks, replies)
    dev = Streamer('192.0.2.1', socket_factory=lambda addr, timeout: fake, read_timeout=0.2)
    dev.connect()
    return dev, fake


def test_split_list_unescapes_items():
    assert split_list('a, b\\, c, d\\(e\\)') == ['a', 'b, c', 'd(e)']
    assert split_list('') == []


def test_preamble_is_parsed_across_chunks():
    dev, _ = connect()
    snap = dev.snapshot()
    assert snap['identity']['Label'] == 'Web Presenter 4K'
    assert snap['protocol'] == '1.2'
    assert snap['settings']['Available Default Platforms'] == ['YouTube RTMP', 'YouTube SRT (Beta)', 'Facebook']
    assert snap['settings']['Available Servers'] == ['Primary', 'US West: Los Angeles, CA']
    assert snap['interfaces'][0]['dhcp'] is True
    assert snap['stream']['status'] == 'Idle'


def test_set_sends_only_given_keys_and_applies_echo():
    dev, fake = connect([(b'STREAM SETTINGS:', b'ACK\n\nSTREAM SETTINGS:\nCurrent Quality Level: Streaming High\n\n')])
    dev.set('STREAM SETTINGS', [('Current Quality Level', 'Streaming High')])
    assert fake.sent.endswith(b'STREAM SETTINGS:\nCurrent Quality Level: Streaming High\n\n')
    assert dev.snapshot()['settings']['Current Quality Level'] == 'Streaming High'


def test_ack_without_blank_line_before_echo():
    dev, _ = connect([(b'STREAM STATE:\n\n', b'ACK\nSTREAM STATE:\nStatus: Streaming\nBitrate: 6000000\n\n')])
    assert dev.state()['stream']['status'] == 'Streaming'
    assert dev.state()['stream']['bitrate'] == 6000000


def test_start_and_stop_send_actions():
    dev, fake = connect([(b'STREAM STATE:\nAction: Start', b'ACK\n\nSTREAM STATE:\nStatus: Connecting\n\n')])
    dev.start()
    assert b'STREAM STATE:\nAction: Start\n\n' in fake.sent
    assert dev.blocks['STREAM STATE']['Status'] == 'Connecting'


def test_nack_raises():
    dev, _ = connect([(b'IDENTITY:', b'NACK\n\n')])
    with pytest.raises(StreamerError, match='refused'):
        dev.set('IDENTITY', {'Label': 'x'})


@pytest.mark.parametrize('block, values', [
    ('NETWORK', {'Dynamic IP': 'false'}),           # not offered: could cut the connection
    ('IDENTITY', {'Model': 'x'}),                   # read only
    ('IDENTITY', {'Label': 'two\nlines'}),          # would break the block framing
])
def test_unwritable_writes_never_reach_the_wire(block, values):
    dev, fake = connect()
    before = fake.sent
    with pytest.raises(StreamerError):
        dev.set(block, values)
    assert fake.sent == before


def test_closed_connection_raises():
    fake = FakeDevice([PREAMBLE, b''])
    dev = Streamer('192.0.2.1', socket_factory=lambda addr, timeout: fake, read_timeout=0.2)
    dev.connect()
    with pytest.raises(StreamerError, match='closed'):
        dev.request('STREAM STATE')
