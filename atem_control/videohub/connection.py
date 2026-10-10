"""The Videohub pages' connections: one per hub, shared by every operator,
closed when nobody has the hub's page open (``atem_control.devicepool``).

The hub ties locks to the TCP session, so locks taken from WebATEM are
shared by everyone on it (as in Bitfocus Companion) and released when the
session closes.
"""
from atem_control.devicepool import DevicePool
from atem_control.videohub.client import Hub

CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 3.0

_PREVIOUS = {}       # ip -> {output: the source it had before our last route}


def _connect(ip):
    hub = Hub(ip, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT)
    hub.connect()
    return hub


def _lost(exc):
    text = str(exc).lower()
    return 'closed' in text or 'not connected' in text


POOL = DevicePool('videohub', _connect, _lost)


def with_hub(ip, fn, viewer=None):
    """Run ``fn(hub)`` on a connected hub at ``ip``; ``viewer`` is the
    polling page's id, which keeps the session open while it watches."""
    return POOL.run(ip, fn, viewer)


def release(ip, viewer):
    return POOL.release(ip, viewer)


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
