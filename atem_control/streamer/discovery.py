"""Streaming encoders on the LAN, from Bonjour ``_blackmagic._tcp``.

Every Blackmagic device answers that service type; an encoder is kept when
its TXT ``class`` or its instance name says Web Presenter / Streaming
Encoder (the class value is not documented, so both are checked). Rides the
ATEM discovery's Zeroconf instance, like the Videohub browser.
"""
import logging
import socket
import threading

from atem_control import discovery as atem_discovery

logger = logging.getLogger(__name__)

SERVICE = '_blackmagic._tcp.local.'
_HINTS = ('web presenter', 'streaming encoder', 'streamingencoder', 'webpresenter', 'streaming bridge')

_registry = {}
_registry_lock = threading.Lock()
_browser = None
_start_lock = threading.Lock()


def _decode(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return '' if value is None else str(value)


def _instance_name(name):
    return name.replace('.' + SERVICE, '').replace(SERVICE, '').rstrip('.')


def looks_like_encoder(name, props):
    text = ' '.join([name] + [str(v) for v in props.values()]).lower()
    return any(h in text for h in _HINTS)


class _Listener:
    def _resolve(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name, timeout=2500)
        except Exception:
            return
        if not info:
            return
        props = {_decode(k).lower(): _decode(v) for k, v in (info.properties or {}).items() if k}
        friendly = _instance_name(name)
        if not looks_like_encoder(friendly, props):
            return
        try:
            addrs = [socket.inet_ntoa(a) for a in info.addresses if len(a) == 4]
        except Exception:
            addrs = []
        if not addrs:
            return
        key = props.get('unique id') or addrs[0]
        with _registry_lock:
            _registry[key] = {'ip': addrs[0], 'name': friendly or addrs[0],
                              'model': props.get('name', '') or props.get('class', '')}

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
            except Exception as e:
                logger.warning('streaming-encoder discovery unavailable: %s', e)
                return False
    return True


def discovered():
    with _registry_lock:
        out = [dict(e, source='mdns') for e in _registry.values()]
    out.sort(key=lambda e: (e['name'] or e['ip']).lower())
    return out
