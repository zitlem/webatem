"""Local addition: atem_control.devicepool, the shared device sessions behind
the Videohub and streaming-encoder pages. A session lives while a page
watches and closes when the last one leaves or goes quiet."""
import pytest

from atem_control import devicepool
from atem_control.devicepool import DevicePool


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Device:
    def __init__(self, ip):
        self.ip, self.closed = ip, False

    def close(self):
        self.closed = True


@pytest.fixture
def pool():
    clock = Clock()
    opened = []

    def connect(ip):
        dev = Device(ip)
        opened.append(dev)
        return dev

    p = DevicePool('test', connect, lost=lambda e: 'closed' in str(e), clock=clock, start_reaper=False)
    p.clock, p.opened = clock, opened
    return p


IP = '192.0.2.20'


def poll(pool, viewer):
    return pool.run(IP, lambda dev: dev, viewer)


def test_one_session_shared_by_viewers(pool):
    assert poll(pool, 'a') is poll(pool, 'b')
    assert len(pool.opened) == 1


def test_last_viewer_leaving_closes_at_once(pool):
    dev = poll(pool, 'a')
    pool.clock.now += 10
    assert pool.release(IP, 'a') is True
    assert dev.closed and not pool.connected(IP)


def test_leaving_keeps_it_open_for_another_watching_page(pool):
    dev = poll(pool, 'a')
    poll(pool, 'b')
    assert pool.release(IP, 'a') is False
    assert not dev.closed
    pool.clock.now += devicepool.RELEASE_GRACE_SECONDS + 1
    assert pool.release(IP, 'b') is True and dev.closed


def test_reaper_closes_a_device_nobody_polls(pool):
    dev = poll(pool, 'a')
    pool.clock.now += devicepool.IDLE_SECONDS - 1
    pool.reap()
    assert not dev.closed                       # still inside the idle window
    pool.clock.now += 2
    pool.reap()
    assert dev.closed and not pool.connected(IP)


def test_polling_keeps_it_open(pool):
    dev = poll(pool, 'a')
    for _ in range(5):
        pool.clock.now += devicepool.IDLE_SECONDS / 2
        poll(pool, 'a')
        pool.reap()
    assert not dev.closed


def test_lost_connection_reconnects_once(pool):
    calls = []

    def flaky(dev):
        calls.append(dev)
        if len(calls) == 1:
            raise RuntimeError('device closed the connection')
        return dev

    second = pool.run(IP, flaky, 'a')
    assert len(pool.opened) == 2 and pool.opened[0].closed and second is pool.opened[1]


def test_device_answer_is_not_retried(pool):
    with pytest.raises(ValueError):
        pool.run(IP, lambda dev: (_ for _ in ()).throw(ValueError('NAK')), 'a')
    assert len(pool.opened) == 1
