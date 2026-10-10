"""One cached Streaming Encoder connection per IP, as
``videohub/connection.py`` does for routers: the page polls once a second
and every reconnect would mean the device's whole preamble again."""
import atexit
import logging
import threading
import time

from atem_control.streamer.client import Streamer, StreamerError

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 3.0
IDLE_CLOSE_SECONDS = 120.0

_DEVICES = {}
_LOCKS = {}
_LAST_USED = {}
_REGISTRY_LOCK = threading.Lock()


def _lock_for(ip):
    with _REGISTRY_LOCK:
        lock = _LOCKS.get(ip)
        if lock is None:
            lock = _LOCKS[ip] = threading.Lock()
        return lock


def _drop(ip):
    dev = _DEVICES.pop(ip, None)
    if dev is not None:
        dev.close()


def _sweep_idle(current_ip):
    now = time.monotonic()
    with _REGISTRY_LOCK:
        stale = [ip for ip in _DEVICES if ip != current_ip
                 and now - _LAST_USED.get(ip, 0.0) > IDLE_CLOSE_SECONDS]
    for ip in stale:
        lock = _lock_for(ip)
        if lock.acquire(blocking=False):
            try:
                if time.monotonic() - _LAST_USED.get(ip, 0.0) > IDLE_CLOSE_SECONDS:
                    _drop(ip)
            finally:
                lock.release()


def _lost(exc):
    text = str(exc).lower()
    return 'closed' in text or 'not connected' in text


def with_streamer(ip, fn):
    """Run ``fn(device)`` on a connected device at ``ip`` under its lock,
    reconnecting once if the cached socket went stale."""
    _sweep_idle(ip)
    with _lock_for(ip):
        _LAST_USED[ip] = time.monotonic()
        last_exc = None
        for _attempt in (1, 2):
            dev = _DEVICES.get(ip)
            if dev is None:
                dev = Streamer(ip, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT)
                dev.connect()
                _DEVICES[ip] = dev
            try:
                return fn(dev)
            except OSError as e:
                logger.warning('streamer %s socket error (%s); reconnecting', ip, e)
                _drop(ip)
                last_exc = e
            except StreamerError as e:
                if not _lost(e):
                    raise
                logger.warning('streamer %s connection lost (%s); reconnecting', ip, e)
                _drop(ip)
                last_exc = e
        raise last_exc


def forget(ip):
    with _lock_for(ip):
        _drop(ip)


def _close_all_at_exit():
    with _REGISTRY_LOCK:
        devices = list(_DEVICES.values())
        _DEVICES.clear()
    for dev in devices:
        dev.close()


atexit.register(_close_all_at_exit)
