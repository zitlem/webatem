"""Recent hubs and salvos, in ``DATA_DIR/videohub.json``.

A JSON file rather than a model: this is a local addition, and a migration
of its own would collide with upstream's numbering on the next update.
Salvos are keyed by the hub's unique id (so they follow the hub to a new
address), falling back to its IP.
"""
import json
import os
import tempfile
import threading
import time

from django.conf import settings

RECENT_MAX = 8
_lock = threading.Lock()


def _path():
    return os.path.join(str(settings.DATA_DIR), 'videohub.json')


def _load():
    try:
        with open(_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault('recent', [])
    data.setdefault('salvos', {})
    return data


def _save(data):
    directory = os.path.dirname(_path())
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.videohub-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, _path())
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def recent():
    with _lock:
        return list(_load()['recent'])


def remember(ip, name='', model=''):
    with _lock:
        data = _load()
        entries = [e for e in data['recent'] if e.get('ip') != ip]
        entries.insert(0, {'ip': ip, 'name': name, 'model': model, 'at': int(time.time())})
        data['recent'] = entries[:RECENT_MAX]
        _save(data)


def salvos(key):
    with _lock:
        return list(_load()['salvos'].get(key, []))


def save_salvo(key, name, routes):
    """Add or replace the salvo called ``name``; returns the hub's salvos."""
    entry = {'name': name, 'routes': [[int(d), int(s)] for d, s in routes],
             'at': int(time.time())}
    with _lock:
        data = _load()
        items = [s for s in data['salvos'].get(key, []) if s.get('name') != name]
        items.append(entry)
        items.sort(key=lambda s: s['name'].lower())
        data['salvos'][key] = items
        _save(data)
        return items


def delete_salvo(key, name):
    with _lock:
        data = _load()
        items = [s for s in data['salvos'].get(key, []) if s.get('name') != name]
        data['salvos'][key] = items
        _save(data)
        return items
