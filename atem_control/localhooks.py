"""This install's WebATEM hooks (local addition), enabled by
``WEBATEM_HOOKS=atem_control.localhooks.LocalHooks`` in the service file.

Upstream names a switcher from Bonjour (mDNS) only, so a switcher Bonjour
has not heard is listed by bare IP on the Connect page for good. Here every
successful connect also records the switcher's own name (its ATEM Setup
name, else its product name) and model in ``DATA_DIR/atem_names.json``, and
``name_for_ip`` falls back to the live session and then to that record.
"""
import json
import logging
import os
import tempfile
import threading

from django.conf import settings

from atem_control.hooks import Hooks

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _path():
    return os.path.join(str(settings.DATA_DIR), 'atem_names.json')


def _load():
    try:
        with open(_path(), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    directory = os.path.dirname(_path())
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.atem-names-', suffix='.json')
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


def _live(ip):
    """(name, model) from the switcher's session if one is open now."""
    try:
        from atemwire.messages.system_info import device_name, product_name
        from atemwire.pool import ATEMInstanceManager
        conn = ATEMInstanceManager.peek_connection(ip)
        if conn is None:
            return '', ''
        mx = conn.mixerstate
        model = product_name(mx)
        return (device_name(mx) or model), model
    except Exception:
        logger.debug('live switcher name unavailable for %s', ip, exc_info=True)
        return '', ''


def remember(ip, name, model=''):
    if not ip or not name:
        return
    with _lock:
        data = _load()
        entry = data.get(ip, {})
        if entry.get('name') == name and (not model or entry.get('model') == model):
            return
        data[ip] = {'name': name, 'model': model or entry.get('model', '')}
        _save(data)


def saved(ip):
    with _lock:
        entry = _load().get(ip) or {}
    return entry.get('name', ''), entry.get('model', '')


class LocalHooks(Hooks):
    def name_for_ip(self, ip):
        name = super().name_for_ip(ip)
        if name:
            return name
        name, _model = _live(ip)
        if name:
            return name
        return saved(ip)[0] or None

    def record_video_mode(self, ip, label):
        # Runs once per successful connect, with the switcher's state in.
        result = super().record_video_mode(ip, label)
        name, model = _live(ip)
        if name:
            try:
                remember(ip, name, model)
            except Exception:
                logger.exception('could not save the name of %s', ip)
        return result

    def record_named(self, ip, name):
        result = super().record_named(ip, name)
        try:
            remember(ip, name, saved(ip)[1])
        except Exception:
            logger.exception('could not save the new name of %s', ip)
        return result
