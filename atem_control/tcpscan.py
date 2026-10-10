"""Subnet sweep for Blackmagic devices with a text control port (local
addition): Videohubs on TCP 9990, streaming encoders on 9977.

The Connect page's Rescan button for devices that Bonjour does not show.
Every host in the subnet gets a short TCP connect; a host that answers is
asked nothing: the device sends its preamble on connect, and the first
couple of kilobytes name it (``Model name`` / ``Friendly name`` on a
Videohub, ``Model`` / ``Label`` on an encoder). The socket is closed at
once, so a sweep holds no session on anything. Subnets are parsed as the
ATEM sweep parses them (``discovery._hosts_for``).
"""
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

from atem_control import discovery as atem_discovery

CONNECT_TIMEOUT = 1.0     # a busy sweep delays answers; 0.35 s missed a hub
READ_TIMEOUT = 1.2
WORKERS = 128
MAX_HOSTS = 1024

_found = {}          # kind -> {ip: {'ip', 'name', 'model', 'source': 'scan'}}
_lock = threading.Lock()


def _identify(ip, port, keys):
    """Connect, read the start of the preamble, close. None if nothing
    listens or the preamble is not the expected kind."""
    try:
        sock = socket.create_connection((ip, port), CONNECT_TIMEOUT)
    except OSError:
        return None
    data = b''
    try:
        sock.settimeout(READ_TIMEOUT)
        while len(data) < 8192 and b'END PRELUDE' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if all(k.encode() in data for k in keys.values()):
                break
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if b'PROTOCOL PREAMBLE' not in data:
        return None
    fields = {}
    for line in data.decode('utf-8', 'replace').splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields.setdefault(key.strip(), value.strip())
    # Blackmagic's Videohub server software answers on 9990 with no router
    # behind it ("Device present: false"): nothing to control there.
    if fields.get('Device present', '').lower() == 'false':
        return None
    return {'ip': ip, 'name': fields.get(keys['name'], '') or ip,
            'model': fields.get(keys['model'], ''), 'source': 'scan'}


KINDS = {
    'videohub': (9990, {'name': 'Friendly name', 'model': 'Model name'}),
    'streamer': (9977, {'name': 'Label', 'model': 'Model'}),
}


def scan(kind, subnet=None, known=None):
    """Sweep ``subnet`` (``192.168.1``, a CIDR, or None for the host's own
    network) for ``kind``; returns ``{'found': [...], 'subnet': label}``."""
    port, keys = KINDS[kind]
    hosts = atem_discovery._hosts_for(subnet)[:MAX_HOSTS]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = [r for r in pool.map(lambda ip: _identify(ip, port, keys), hosts) if r]
    # A device found before (or named by the caller) can miss a busy sweep
    # (seen with a Smart Videohub 40x40): ask each such one again, alone.
    got = {r['ip'] for r in results}
    with _lock:
        again = set(_found.get(kind, {})) | set(known or ())
    for ip in sorted((again & set(hosts)) - got):
        r = _identify(ip, port, keys)
        if r:
            results.append(r)
    with _lock:
        known = _found.setdefault(kind, {})
        for r in results:
            known[r['ip']] = r
    return {'found': sorted(results, key=lambda r: r['ip']),
            'subnet': subnet or atem_discovery.local_subnet()}


def found(kind):
    """Devices earlier sweeps found, for the Connect page's list."""
    with _lock:
        return list(_found.get(kind, {}).values())
