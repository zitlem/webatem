"""Videohubs on the LAN, from Bonjour ``_videohub._tcp``.

Rides the Zeroconf instance the ATEM discovery already runs (started
lazily by the Connect page's first poll), with a second browser for this
service type. The instance name is the hub's friendly name.
"""
import logging
import socket
import threading

from atem_control import discovery as atem_discovery

logger = logging.getLogger(__name__)

SERVICE = '_videohub._tcp.local.'

_registry = {}       # unique id or ip -> {'ip', 'name', 'model'}
_registry_lock = threading.Lock()
_browser = None
_start_lock = threading.Lock()


def _decode(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return '' if value is None else str(value)


def _instance_name(name):
    return name.replace('.' + SERVICE, '').replace(SERVICE, '').rstrip('.')


class _Listener:
    def _resolve(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name, timeout=2500)
        except Exception:
            return
        if not info:
            return
        try:
            addrs = [socket.inet_ntoa(a) for a in info.addresses if len(a) == 4]
        except Exception:
            addrs = []
        if not addrs:
            return
        props = {_decode(k).lower(): _decode(v) for k, v in (info.properties or {}).items() if k}
        friendly = _instance_name(name)
        key = props.get('unique id') or addrs[0]
        with _registry_lock:
            _registry[key] = {'ip': addrs[0], 'name': friendly or addrs[0],
                              'model': props.get('name', '') or friendly}

    def add_service(self, zc, type_, name):
        self._resolve(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._resolve(zc, type_, name)

    def remove_service(self, zc, type_, name):
        friendly = _instance_name(name)
        with _registry_lock:
            for key, entry in list(_registry.items()):
                if entry['name'] == friendly:
                    del _registry[key]


def ensure_started():
    """Start the ``_videohub._tcp`` browser once. False if mDNS is unavailable."""
    global _browser
    if _browser is not None:
        return True
    if not atem_discovery.ensure_mdns_started():
        return False
    with _start_lock:
        if _browser is None:
            zc = getattr(atem_discovery, '_zeroconf', None)
            if zc is None:
                return False
            try:
                from zeroconf import ServiceBrowser
                _browser = ServiceBrowser(zc, SERVICE, _Listener())
                logger.info('Videohub mDNS discovery started (%s)', SERVICE)
            except Exception as e:
                logger.warning('Videohub mDNS discovery unavailable: %s', e)
                return False
    return True


def discovered_hubs():
    with _registry_lock:
        out = [dict(e, source='mdns') for e in _registry.values()]
    out.sort(key=lambda e: (e['name'] or e['ip']).lower())
    return out
