"""Local addition: the SuperSource and ATEM stream/record endpoints, on a
fake pooled connection holding real atemwire state objects. Checks what
reaches the wire (atemwire's CSBP / CSSc / StrR) and the range checks."""
import json
import struct
from unittest import mock

import pytest

from atemwire.messages.streaming import StreamingStatusField
from atemwire.messages.supersource import SupersourceBoxPropertiesField, SupersourcePropertiesField

IP = '192.0.2.10'


def _box(ssrc, box, x, y):
    return SupersourceBoxPropertiesField(
        struct.pack('>BB?xH hhH ?x HHHH 2x', ssrc, box, True, box + 1, x, y, 500, False, 0, 0, 0, 0))


class _Topology:
    supersources = 1


class FakeConn:
    def __init__(self):
        self.sent = []
        self.mixerstate = {
            'topology': _Topology(),
            'supersource-box-properties': {0: {b: _box(0, b, -800 + 1600 * (b % 2), 450 - 900 * (b // 2)) for b in range(4)}},
            'supersource-properties': {0: SupersourcePropertiesField(
                struct.pack('>BxH HB? HH ?xxx', 0, 3010, 3011, 0, False, 500, 700, False))},
        }

    def send(self, cmd):
        self.sent.append(cmd.get_command())


@pytest.fixture
def conn():
    fake = FakeConn()
    with mock.patch('atemwire.pool.ATEMInstanceManager.peek_connection', return_value=fake), \
         mock.patch('atem_control.supersource.views.build_full_state',
                    return_value={'sources': [{'source': 1, 'short': 'CAM1', 'long': 'Camera 1'}]}):
        yield fake


def _post(client, url, body):
    return client.post(url, json.dumps(body), content_type='application/json')


def test_state_reports_boxes_and_art(client, conn):
    data = client.get(f'/atem/supersource/state/?ip={IP}').json()
    ssrc = data['supersources'][0]
    assert (ssrc['boxes'][0]['x'], ssrc['boxes'][0]['y'], ssrc['boxes'][0]['size']) == (-800, 450, 500)
    assert ssrc['art']['fill_source'] == 3010 and ssrc['art']['gain'] == 700
    assert data['sources'][0]['short'] == 'CAM1'


def test_box_write_sends_only_the_changed_fields(client, conn):
    assert _post(client, '/atem/supersource/box/', {'ip': IP, 'box': 2, 'props': {'x': 1234, 'size': 600}}).status_code == 200
    wire = conn.sent[-1]
    payload = wire[wire.index(b'CSBP') + 4:]
    mask, index, box = struct.unpack('>HBB', payload[:4])
    assert mask == (1 << 2) | (1 << 4) and index == 0 and box == 2
    x, = struct.unpack('>h', payload[8:10])
    size, = struct.unpack('>H', payload[12:14])
    assert (x, size) == (1234, 600)


def test_preset_sends_one_command_per_box(client, conn):
    boxes = [{'box': i, 'props': {'enabled': i < 2}} for i in range(4)]
    assert _post(client, '/atem/supersource/box/', {'ip': IP, 'boxes': boxes}).status_code == 200
    assert len(conn.sent) == 4


@pytest.mark.parametrize('props', [{'x': 99999}, {'size': 10}, {'bogus': 1}, {'top': 'abc'}])
def test_box_write_out_of_range_is_refused(client, conn, props):
    assert _post(client, '/atem/supersource/box/', {'ip': IP, 'box': 0, 'props': props}).status_code == 400
    assert conn.sent == []


def test_art_write(client, conn):
    assert _post(client, '/atem/supersource/art/', {'ip': IP, 'props': {'layer': 1, 'clip': 250}}).status_code == 200
    assert b'CSSc' in conn.sent[-1]


def test_not_connected_is_409(client):
    with mock.patch('atemwire.pool.ATEMInstanceManager.peek_connection', return_value=None):
        assert client.get(f'/atem/supersource/state/?ip={IP}').status_code == 409
        assert client.get(f'/atem/stream/state/?ip={IP}').status_code == 409


def test_stream_panel_hidden_without_streaming_state(client, conn):
    assert client.get(f'/atem/stream/state/?ip={IP}').json() == {'has_streaming': False, 'has_recording': False}


def test_stream_status_and_stop(client, conn):
    conn.mixerstate['streaming-status'] = StreamingStatusField(struct.pack('>hxx', 4))
    state = client.get(f'/atem/stream/state/?ip={IP}').json()
    assert state['has_streaming'] and state['streaming']['status'] == 'on_air'
    assert _post(client, '/atem/stream/action/', {'ip': IP, 'action': 'stop_stream'}).status_code == 200
    assert b'StrR' in conn.sent[-1]


def test_bad_ip_is_400(client):
    assert client.get('/atem/supersource/state/?ip=not-an-ip').status_code == 400
