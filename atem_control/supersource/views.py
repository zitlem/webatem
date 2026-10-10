"""``/atem/supersource/…``: state of every SuperSource on the connected
switcher, and the box / art writes.

The page polls ``state`` while the panel is open; writes answer with the
same snapshot so a box never shows a value the switcher has not echoed.
"""
import json
import logging

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from atem_control.hooks import access_required
from atem_control.netutil import is_valid_ip
from atemwire.messages import supersource as ssrc_ops
from atemwire.pool import ATEMInstanceManager
from atemwire.state import build_full_state

logger = logging.getLogger(__name__)

BOXES = 4

# Writable box fields: name -> (kind, low, high). Ranges from atemwire's CSBP
# docstring (position in 1/100 of a box unit, size in 1/1000).
BOX_FIELDS = {
    'enabled': ('bool', None, None),
    'source':  ('int', 0, 65535),
    'x':       ('int', -4800, 4800),
    'y':       ('int', -3400, 3400),
    'size':    ('int', 70, 1000),
    'masked':  ('bool', None, None),
    'top':     ('int', 0, 18000),
    'bottom':  ('int', 0, 18000),
    'left':    ('int', 0, 32000),
    'right':   ('int', 0, 32000),
}

ART_FIELDS = {
    'fill_source':   ('int', 0, 65535),
    'key_source':    ('int', 0, 65535),
    'layer':         ('int', 0, 1),       # 0 background, 1 foreground
    'premultiplied': ('bool', None, None),
    'clip':          ('int', 0, 1000),
    'gain':          ('int', 0, 1000),
    'invert':        ('bool', None, None),
}


class _Bad(Exception):
    pass


def _clean(props, fields):
    """Validate and coerce a ``{field: value}`` dict against ``fields``."""
    if not isinstance(props, dict) or not props:
        raise _Bad('props required')
    out = {}
    for name, value in props.items():
        if name not in fields:
            raise _Bad(f'unknown field {name}')
        kind, low, high = fields[name]
        if kind == 'bool':
            out[name] = bool(value)
            continue
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            raise _Bad(f'{name} must be a number')
        if not low <= number <= high:
            raise _Bad(f'{name} must be between {low} and {high}')
        out[name] = number
    return out


def _connection(ip):
    conn = ATEMInstanceManager.peek_connection(ip)
    if conn is None:
        return None
    return conn


def _count(mx):
    topology = mx.get('topology')
    count = getattr(topology, 'supersources', 0) if topology is not None else 0
    boxes = mx.get('supersource-box-properties') or {}
    # Older firmware may not report the count; boxes on the wire prove one.
    return max(int(count or 0), len(boxes))


def snapshot(conn):
    mx = conn.mixerstate
    boxes_by_ssrc = mx.get('supersource-box-properties') or {}
    art_by_ssrc = mx.get('supersource-properties') or {}
    supersources = []
    for index in range(_count(mx)):
        boxes = []
        for box in range(BOXES):
            f = (boxes_by_ssrc.get(index) or {}).get(box)
            if f is None:
                boxes.append({'box': box, 'known': False})
                continue
            boxes.append({
                'box': box, 'known': True, 'enabled': bool(f.enabled),
                'source': f.source, 'x': f.x, 'y': f.y, 'size': f.size,
                'masked': bool(f.masked), 'top': f.mask_top, 'bottom': f.mask_bottom,
                'left': f.mask_left, 'right': f.mask_right,
            })
        a = art_by_ssrc.get(index)
        art = None
        if a is not None:
            art = {'fill_source': a.fill_source, 'key_source': a.key_source,
                   'layer': a.layer, 'premultiplied': bool(a.premultiplied),
                   'clip': a.clip, 'gain': a.gain, 'invert': bool(a.inverted)}
        supersources.append({'index': index, 'boxes': boxes, 'art': art})
    try:
        sources = [{'source': s['source'], 'short': s.get('short', ''), 'long': s.get('long', '')}
                   for s in build_full_state(conn).get('sources', [])]
    except Exception:
        logger.exception('supersource: source list unavailable')
        sources = []
    return {'supersources': supersources, 'sources': sources}


def _answer(fn):
    try:
        return fn()
    except _Bad as e:
        return HttpResponseBadRequest(str(e))


def _log(ip, action, summary, **extra):
    try:
        from atem_control.activity import ActivityLog, record_activity
        record_activity(feature=ActivityLog.FEATURE_ATEM_CONTROL,
                        device=ActivityLog.DEVICE_ATEM, action=f'supersource_{action}',
                        target=ip, summary=summary, **extra)
    except Exception:
        logger.exception('supersource activity log failed')


def _ip(raw):
    ip = (raw or '').strip()
    if not is_valid_ip(ip):
        raise _Bad('valid ip required')
    return ip


@require_GET
@access_required
def supersource_state(request):
    def run():
        conn = _connection(_ip(request.GET.get('ip')))
        if conn is None:
            return JsonResponse({'error': 'switcher not connected'}, status=409)
        return JsonResponse(snapshot(conn))
    return _answer(run)


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        raise _Bad('invalid json')


def _ssrc_index(body, conn):
    index = int(body.get('ssrc', 0))
    if not 0 <= index < max(1, _count(conn.mixerstate)):
        raise _Bad('no such SuperSource')
    return index


@require_POST
@access_required
def supersource_box(request):
    """Body ``{ip, ssrc, box, props}``; ``boxes: [{box, props}, …]`` sets
    several at once (a layout preset)."""
    def run():
        body = _body(request)
        ip = _ip(body.get('ip'))
        conn = _connection(ip)
        if conn is None:
            return JsonResponse({'error': 'switcher not connected'}, status=409)
        index = _ssrc_index(body, conn)
        items = body.get('boxes')
        if items is None:
            items = [{'box': body.get('box'), 'props': body.get('props')}]
        cleaned = []
        for item in items:
            box = int(item.get('box'))
            if not 0 <= box < BOXES:
                raise _Bad('box must be 0-3')
            cleaned.append((box, _clean(item.get('props'), BOX_FIELDS)))
        for box, props in cleaned:
            ssrc_ops.set_supersource_box(conn, box, index=index, **props)
        if not body.get('drag'):
            _log(ip, 'box', f'SuperSource {index + 1}: '
                 + '; '.join(f"box {b + 1} {', '.join(f'{k}={v}' for k, v in p.items())}" for b, p in cleaned))
        return JsonResponse({'ok': True})
    return _answer(run)


@require_POST
@access_required
def supersource_art(request):
    """Body ``{ip, ssrc, props}`` with art / keyer fields."""
    def run():
        body = _body(request)
        ip = _ip(body.get('ip'))
        conn = _connection(ip)
        if conn is None:
            return JsonResponse({'error': 'switcher not connected'}, status=409)
        index = _ssrc_index(body, conn)
        props = _clean(body.get('props'), ART_FIELDS)
        ssrc_ops.set_supersource_properties(conn, index=index, **props)
        if not body.get('drag'):
            _log(ip, 'art', f"SuperSource {index + 1} art: {', '.join(f'{k}={v}' for k, v in props.items())}")
        return JsonResponse({'ok': True})
    return _answer(run)
