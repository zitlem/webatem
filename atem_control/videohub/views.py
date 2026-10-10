"""The Videohub page and its JSON API (``/atem/videohub/…``).

Plain sync views over ``with_hub``, like the HyperDeck endpoints: an open
LAN tool with the control page's trust model. Every change is logged as
activity, and every answer carries the hub's fresh state so the page never
shows a route the hub has not acknowledged.
"""
import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from atem_control import discovery as atem_discovery, tcpscan
from atem_control.hooks import access_required
from atem_control.netutil import is_valid_ip
from atem_control.videohub import discovery, store
from atem_control.videohub.client import LOCK_MODES
from atem_control.videohub.connection import (
    previous_map, previous_source, release, remember_previous, with_hub)
from videohubwire import VideohubError

logger = logging.getLogger(__name__)

LABEL_KINDS = ('input', 'output')


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


def _snapshot(ip, hub):
    snap = hub.state()
    snap['ip'] = ip
    snap['previous'] = {str(k): v for k, v in previous_map(ip).items()}
    return snap


def _viewer(raw):
    """The polling page's id (random, from the page), or None."""
    value = str(raw or '')[:40]
    return value if value.replace('-', '').isalnum() else None


def _salvo_key(hub, ip):
    return hub.device.get('unique id') or ip


def _answer(fn):
    """Common error handling: 400 for bad requests, 502 for hub failures."""
    try:
        return fn()
    except _Bad as e:
        return HttpResponseBadRequest(str(e))
    except (KeyError, ValueError, TypeError) as e:
        return HttpResponseBadRequest(f'bad request: {e}')
    except (OSError, VideohubError) as e:
        return JsonResponse({'error': str(e)}, status=502)


def _log(request, ip, action, summary, **extra):
    try:
        from atem_control.activity import ActivityLog, record_activity
        record_activity(feature=ActivityLog.FEATURE_ATEM_CONTROL,
                        device=ActivityLog.DEVICE_VIDEOHUB,
                        action=f'videohub_{action}', target=ip,
                        summary=summary, **extra)
    except Exception:
        logger.exception('videohub activity log failed')


@ensure_csrf_cookie
@access_required
def videohub_page(request):
    ip = (request.GET.get('ip') or '').strip()
    return render(request, 'videohub/control.html', {
        'hub_ip': ip if is_valid_ip(ip) else '',
    })


@require_GET
@access_required
def videohub_discovered(request):
    discovery.ensure_started()
    return JsonResponse({'hubs': _merge(discovery.discovered_hubs(), tcpscan.found('videohub')),
                         'recent': store.recent(), 'subnet': atem_discovery.local_subnet()})


@require_GET
@access_required
def videohub_state(request):
    def run():
        ip = _ip(request.GET.get('ip'))
        viewer = _viewer(request.GET.get('viewer'))
        return JsonResponse(with_hub(ip, lambda hub: _snapshot(ip, hub), viewer))
    return _answer(run)


@require_POST
@access_required
def videohub_open(request):
    """First load of a hub: state plus recording it under Recent."""
    def run():
        body = _body(request)
        ip = _ip(body.get('ip'))
        snap = with_hub(ip, lambda hub: _snapshot(ip, hub), _viewer(body.get('viewer')))
        dev = snap['device']
        store.remember(ip, dev.get('friendly_name', ''), dev.get('model_name', ''))
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def videohub_route(request):
    """Body ``{ip, routes: [[dest, src], …]}``: one pair is a route, several
    a salvo (sent as one block)."""
    def run():
        body = _body(request)
        ip = _ip(body.get('ip'))
        routes = [(int(d), int(s)) for d, s in body.get('routes') or []]
        if not routes:
            raise _Bad('routes required')

        def go(hub):
            remember_previous(ip, hub, [d for d, _ in routes])
            if len(routes) == 1:
                hub.route(*routes[0])
            else:
                hub.route_many(routes)
            return _snapshot(ip, hub)

        snap = with_hub(ip, go, _viewer(body.get('viewer')))
        names = {o['index']: o['label'] for o in snap['outputs']}
        srcs = {i['index']: i['label'] for i in snap['inputs']}
        text = ', '.join(f"{srcs.get(s, s)} → {names.get(d, d)}" for d, s in routes)
        _log(request, ip, 'route', f'Videohub {ip}: {text}', routes=routes)
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def videohub_previous(request):
    """Route an output back to the source it had before our last route."""
    def run():
        body = _body(request)
        ip, dest = _ip(body.get('ip')), int(body['dest'])
        src = previous_source(ip, dest)
        if src is None:
            raise _Bad('no previous route for this output')

        def go(hub):
            remember_previous(ip, hub, [dest])
            hub.route(dest, src)
            return _snapshot(ip, hub)

        snap = with_hub(ip, go, _viewer(body.get('viewer')))
        _log(request, ip, 'previous', f'Videohub {ip}: output {dest + 1} back to input {src + 1}')
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def videohub_lock(request):
    """Body ``{ip, dest, mode}``; mode is lock, unlock or force."""
    def run():
        body = _body(request)
        ip, dest, mode = _ip(body.get('ip')), int(body['dest']), body.get('mode')
        if mode not in LOCK_MODES:
            raise _Bad('mode must be lock, unlock or force')

        def go(hub):
            hub.set_lock(dest, mode)
            return _snapshot(ip, hub)

        snap = with_hub(ip, go, _viewer(body.get('viewer')))
        _log(request, ip, f'lock_{mode}', f'Videohub {ip}: {mode} output {dest + 1}')
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def videohub_label(request):
    """Body ``{ip, kind: input|output, index, label}``; saved on the hub."""
    def run():
        body = _body(request)
        ip, kind, index = _ip(body.get('ip')), body.get('kind'), int(body['index'])
        label = str(body.get('label', ''))
        if kind not in LABEL_KINDS:
            raise _Bad('kind must be input or output')

        def go(hub):
            if kind == 'input':
                hub.set_input_label(index, label)
            else:
                hub.set_output_label(index, label)
            return _snapshot(ip, hub)

        snap = with_hub(ip, go, _viewer(body.get('viewer')))
        _log(request, ip, 'label', f'Videohub {ip}: {kind} {index + 1} renamed "{label}"')
        return JsonResponse(snap)
    return _answer(run)


@require_http_methods(['GET', 'POST', 'DELETE'])
@access_required
def videohub_salvos(request):
    """GET ``?ip=``: the hub's salvos. POST ``{ip, name, routes?}``: save
    (``routes`` omitted = the hub's whole current routing). DELETE
    ``{ip, name}``: remove."""
    def run():
        if request.method == 'GET':
            ip = _ip(request.GET.get('ip'))
            key = with_hub(ip, lambda hub: _salvo_key(hub, ip))
            return JsonResponse({'salvos': store.salvos(key)})
        body = _body(request)
        ip = _ip(body.get('ip'))
        name = ' '.join(str(body.get('name', '')).split())[:64]
        if not name:
            raise _Bad('name required')

        def key_and_routes(hub):
            hub.state()
            current = [[d, s] for d, s in sorted(hub.routing.items())]
            return _salvo_key(hub, ip), current

        key, current = with_hub(ip, key_and_routes)
        if request.method == 'DELETE':
            return JsonResponse({'salvos': store.delete_salvo(key, name)})
        routes = body.get('routes') or current
        items = store.save_salvo(key, name, routes)
        _log(request, ip, 'salvo_save', f'Videohub {ip}: saved salvo "{name}"')
        return JsonResponse({'salvos': items})
    return _answer(run)


def _routes_text(snap):
    """Routing and labels as the hub's own protocol blocks: readable, and
    the same text a Videohub sends, so import is the same parser."""
    lines = [f"# {snap['device'].get('friendly_name', '')} "
             f"({snap['device'].get('model_name', '')}), saved from WebATEM", '']
    lines.append('INPUT LABELS:')
    lines += [f"{i['index']} {i['label']}" for i in snap['inputs']]
    lines += ['', 'OUTPUT LABELS:']
    lines += [f"{o['index']} {o['label']}" for o in snap['outputs']]
    lines += ['', 'VIDEO OUTPUT ROUTING:']
    lines += [f"{o['index']} {o['source']}" for o in snap['outputs'] if o['source'] is not None]
    return '\n'.join(lines) + '\n\n'


def parse_routes_text(text):
    """The ``VIDEO OUTPUT ROUTING`` pairs in a saved routes file."""
    routes, in_block = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line.endswith(':') and not line[:1].isdigit():
            in_block = line == 'VIDEO OUTPUT ROUTING:'
            continue
        if not in_block or not line or line.startswith('#'):
            continue
        dest, _, src = line.partition(' ')
        routes.append((int(dest), int(src.strip())))
    return routes


@require_http_methods(['GET', 'POST'])
@access_required
def videohub_routes_file(request):
    """GET ``?ip=``: download routing + labels. POST ``{ip, text}``: apply
    the file's routing (labels in it are left alone)."""
    def run():
        if request.method == 'GET':
            ip = _ip(request.GET.get('ip'))
            snap = with_hub(ip, lambda hub: _snapshot(ip, hub))
            name = (snap['device'].get('friendly_name') or ip).replace(' ', '_')
            resp = HttpResponse(_routes_text(snap), content_type='text/plain; charset=utf-8')
            resp['Content-Disposition'] = f'attachment; filename="{name}-routes.txt"'
            return resp
        body = _body(request)
        ip = _ip(body.get('ip'))
        routes = parse_routes_text(str(body.get('text', '')))
        if not routes:
            raise _Bad('no VIDEO OUTPUT ROUTING block in the file')

        def go(hub):
            remember_previous(ip, hub, [d for d, _ in routes])
            hub.route_many(routes)
            return _snapshot(ip, hub)

        snap = with_hub(ip, go, _viewer(body.get('viewer')))
        _log(request, ip, 'routes_import', f'Videohub {ip}: loaded {len(routes)} routes from a file')
        return JsonResponse(snap)
    return _answer(run)


@require_POST
@access_required
def videohub_release(request):
    """Body ``{ip, viewer}``: this page is leaving. The hub session closes
    unless another page is still watching it."""
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
def videohub_scan(request):
    """Rescan ``?subnet=192.168.1`` (or the host's own network) for
    devices Bonjour does not show; each answering host is identified from
    its preamble and the socket closed at once."""
    subnet = (request.GET.get('subnet') or '').strip() or None
    known = [e['ip'] for e in discovery.discovered_hubs()] + [e['ip'] for e in store.recent()]
    return JsonResponse(tcpscan.scan('videohub', subnet, known))
