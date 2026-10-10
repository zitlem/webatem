"""The streaming-encoder page and its JSON API (``/atem/streamer/…``)."""
import json
import logging

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from atem_control import discovery as atem_discovery, tcpscan
from atem_control.hooks import access_required
from atem_control.netutil import is_valid_ip
from atem_control.streamer import discovery, store
from atem_control.streamer.client import WRITABLE, StreamerError
from atem_control.streamer.connection import forget, release, with_streamer

logger = logging.getLogger(__name__)


class _Bad(Exception):
    pass


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        raise _Bad('invalid json')


def _ip(raw):
    ip = (raw or '').strip()
    if not is_valid_ip(ip):
        raise _Bad('valid ip required')
    return ip


def _viewer(raw):
    """The polling page's id (random, from the page), or None."""
    value = str(raw or '')[:40]
    return value if value.replace('-', '').isalnum() else None


def _snapshot(ip, dev):
    snap = dev.state()
    snap['ip'] = ip
    return snap


def _answer(fn):
    try:
        return fn()
    except _Bad as e:
        return HttpResponseBadRequest(str(e))
    except (KeyError, ValueError, TypeError) as e:
        return HttpResponseBadRequest(f'bad request: {e}')
    except (OSError, StreamerError) as e:
        return JsonResponse({'error': str(e)}, status=502)


def _log(ip, action, summary):
    try:
        from atem_control.activity import ActivityLog, record_activity
        record_activity(feature=ActivityLog.FEATURE_ATEM_CONTROL,
                        device=ActivityLog.DEVICE_STREAMER, action=f'streamer_{action}',
                        target=ip, summary=summary)
    except Exception:
        logger.exception('streamer activity log failed')


@ensure_csrf_cookie
@access_required
def streamer_page(request):
    ip = (request.GET.get('ip') or '').strip()
    return render(request, 'streamer/control.html', {'device_ip': ip if is_valid_ip(ip) else ''})


@require_GET
@access_required
def streamer_discovered(request):
    discovery.ensure_started()
    return JsonResponse({'devices': _merge(discovery.discovered(), tcpscan.found('streamer')),
                         'recent': store.recent(), 'subnet': atem_discovery.local_subnet()})


@require_POST
@access_required
def streamer_open(request):
    def run():
        body = _body(request)
        ip = _ip(body.get('ip'))
        snap = with_streamer(ip, lambda dev: _snapshot(ip, dev), _viewer(body.get('viewer')))
        ident = snap['identity']
        store.remember(ip, ident.get('Label', ''), ident.get('Model', ''))
        return JsonResponse(snap)
    return _answer(run)


@require_GET
@access_required
def streamer_state(request):
    def run():
        ip = _ip(request.GET.get('ip'))
        viewer = _viewer(request.GET.get('viewer'))
        return JsonResponse(with_streamer(ip, lambda dev: _snapshot(ip, dev), viewer))
    return _answer(run)


@require_POST
@access_required
def streamer_stream(request):
    """Body ``{ip, action: start|stop}``."""
    def run():
        body = _body(request)
        ip, action = _ip(body.get('ip')), body.get('action')
        if action not in ('start', 'stop'):
            raise _Bad('action must be start or stop')

        def go(dev):
            dev.start() if action == 'start' else dev.stop()
            return _snapshot(ip, dev)

        snap = with_streamer(ip, go, _viewer(body.get('viewer')))
        _log(ip, action, f"{'Started' if action == 'start' else 'Stopped'} streaming on "
             f"{snap['identity'].get('Label') or ip}")
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def streamer_settings(request):
    """Body ``{ip, block, values: [[key, value], …]}`` (order kept: the
    platform goes first, the device then offers its servers and qualities)."""
    def run():
        body = _body(request)
        ip, block = _ip(body.get('ip')), body.get('block')
        if block not in WRITABLE:
            raise _Bad('block not writable')
        values = [(str(k), str(v)) for k, v in body.get('values') or []]
        if not values:
            raise _Bad('values required')
        order = {k: i for i, k in enumerate(WRITABLE[block])}
        values.sort(key=lambda kv: order.get(kv[0], 99))

        def go(dev):
            dev.set(block, values)
            return _snapshot(ip, dev)

        snap = with_streamer(ip, go, _viewer(body.get('viewer')))
        shown = ', '.join(k if 'Key' in k or 'Password' in k else f'{k}={v}' for k, v in values)
        _log(ip, 'settings', f'{block} on {snap["identity"].get("Label") or ip}: {shown}')
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def streamer_reboot(request):
    def run():
        ip = _ip(_body(request).get('ip'))
        with_streamer(ip, lambda dev: dev.reboot())
        forget(ip)
        _log(ip, 'reboot', f'Rebooted streaming encoder {ip}')
        return JsonResponse({'ok': True})
    return _answer(run)


@require_POST
@access_required
def streamer_release(request):
    """Body ``{ip, viewer}``: this page is leaving; the session closes
    unless another page is still watching the encoder."""
    def run():
        body = _body(request)
        ip, viewer = _ip(body.get('ip')), _viewer(body.get('viewer'))
        if not viewer:
            raise _Bad('viewer required')
        return JsonResponse({'closed': release(ip, viewer)})
    return _answer(run)


def _merge(bonjour, swept):
    """Bonjour entries first; swept ones add what Bonjour did not see."""
    seen = {e['ip'] for e in bonjour}
    return bonjour + sorted((e for e in swept if e['ip'] not in seen), key=lambda e: e['ip'])


@require_GET
@access_required
def streamer_scan(request):
    """Rescan ``?subnet=192.168.1`` (or the host's own network) for
    devices Bonjour does not show; each answering host is identified from
    its preamble and the socket closed at once."""
    subnet = (request.GET.get('subnet') or '').strip() or None
    known = [e['ip'] for e in discovery.discovered()] + [e['ip'] for e in store.recent()]
    return JsonResponse(tcpscan.scan('streamer', subnet, known))
