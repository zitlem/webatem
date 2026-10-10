"""The streaming-encoder pages' connections: one per device, shared, closed
when nobody has its page open (``atem_control.devicepool``)."""
from atem_control.devicepool import DevicePool
from atem_control.streamer.client import Streamer, StreamerError

CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 3.0


def _connect(ip):
    dev = Streamer(ip, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT)
    dev.connect()
    return dev


def _lost(exc):
    text = str(exc).lower()
    return isinstance(exc, StreamerError) and ('closed' in text or 'not connected' in text)


POOL = DevicePool('streamer', _connect, _lost)


def with_streamer(ip, fn, viewer=None):
    return POOL.run(ip, fn, viewer)


def release(ip, viewer):
    return POOL.release(ip, viewer)


def forget(ip):
    POOL.forget(ip)
