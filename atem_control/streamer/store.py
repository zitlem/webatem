"""Recent streaming encoders, in ``DATA_DIR/streamer.json``."""
import json
import os
import tempfile
import threading
import time

from django.conf import settings

RECENT_MAX = 8
_lock = threading.Lock()


def _path():
    return os.path.join(str(settings.DATA_DIR), 'streamer.json')


def _load():
    try:
        with open(_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault('recent', [])
    return data


def _save(data):
    directory = os.path.dirname(_path())
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.streamer-', suffix='.json')
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
