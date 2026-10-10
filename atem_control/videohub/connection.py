"""One cached Videohub connection per IP, as hyperdeck/connection.py does
for decks: the page polls ``state`` about once a second, so reconnecting per
request would mean a full preamble (every label and route) each time.

A cached connection is also the lock owner: the hub ties a lock to the TCP
session, so locks taken from WebATEM are shared by every operator on it, as
in Bitfocus Companion. Idle hubs are closed after ``HUB_IDLE_CLOSE_SECONDS``
(their locks with them); every hub is closed at exit.
"""
import atexit
import logging
import threading
import time

from atem_control.videohub.client import Hub

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 3.0
HUB_IDLE_CLOSE_SECONDS = 300.0

_HUBS = {}           # ip -> Hub
_LOCKS = {}          # ip -> threading.Lock (one in-flight command per hub)
_LAST_USED = {}      # ip -> time.monotonic()
_PREVIOUS = {}       # ip -> {output: the source it had before our last route}
_REGISTRY_LOCK = threading.Lock()


def _lock_for(ip):
    with _REGISTRY_LOCK:
        lock = _LOCKS.get(ip)
        if lock is None:
            lock = _LOCKS[ip] = threading.Lock()
        return lock


def _connect(ip):
    hub = Hub(ip, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT)
    hub.connect()
    return hub


def _drop(ip):
    hub = _HUBS.pop(ip, None)
    if hub is not None:
        try:
            hub.close()
        except Exception:
            pass


def _sweep_idle(current_ip):
    now = time.monotonic()
    with _REGISTRY_LOCK:
        stale = [ip for ip in _HUBS if ip != current_ip
                 and now - _LAST_USED.get(ip, 0.0) > HUB_IDLE_CLOSE_SECONDS]
    for ip in stale:
        lock = _lock_for(ip)
        if not lock.acquire(blocking=False):
            continue
        try:
            if time.monotonic() - _LAST_USED.get(ip, 0.0) > HUB_IDLE_CLOSE_SECONDS:
                logger.info('videohub %s idle; closing cached session', ip)
                _drop(ip)
        finally:
            lock.release()


def with_hub(ip, fn):
    """Run ``fn(hub)`` on a connected hub at ``ip`` under its lock.

    Reconnects once when the cached socket has gone stale (``OSError``, or
    the library's "connection closed"); any other ``VideohubError`` (a NAK)
    is the hub's answer and propagates.
    """
    _sweep_idle(ip)
    with _lock_for(ip):
        _LAST_USED[ip] = time.monotonic()
        last_exc = None
        for _attempt in (1, 2):
            hub = _HUBS.get(ip)
            if hub is None:
                hub = _HUBS[ip] = _connect(ip)
            try:
                return fn(hub)
            except OSError as e:
                logger.warning('videohub %s socket error (%s); reconnecting', ip, e)
                _drop(ip)
                last_exc = e
            except Exception as e:
                if 'closed' in str(e).lower() or 'not connected' in str(e).lower():
                    logger.warning('videohub %s connection lost (%s); reconnecting', ip, e)
                    _drop(ip)
                    last_exc = e
                    continue
                raise
        raise last_exc


def remember_previous(ip, hub, dests):
    """Record each output's current source before routing it elsewhere."""
    prev = _PREVIOUS.setdefault(ip, {})
    for dest in dests:
        src = hub.routing.get(int(dest))
        if src is not None:
            prev[int(dest)] = src


def previous_source(ip, dest):
    return _PREVIOUS.get(ip, {}).get(int(dest))


def previous_map(ip):
    return dict(_PREVIOUS.get(ip, {}))


def _close_all_at_exit():
    with _REGISTRY_LOCK:
        hubs = list(_HUBS.values())
        _HUBS.clear()
    for hub in hubs:
        try:
            hub.close()
        except Exception:
            pass


atexit.register(_close_all_at_exit)
