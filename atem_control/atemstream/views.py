"""``/atem/stream/…``: ATEM built-in streaming / recording state and control,
on the control page's own session (``peek_connection``)."""
import json
import logging

from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from atem_control.hooks import access_required
from atem_control.netutil import is_valid_ip
from atemwire.messages import recording, streaming
from atemwire.pool import ATEMInstanceManager

logger = logging.getLogger(__name__)

# StRS status values (atemwire): -1 unknown, 0 nothing, 1 idle,
# 2 connecting, 4 on air, 22/36 stopping.
STREAM_STATUS = {1: 'idle', 2: 'connecting', 4: 'on_air', 22: 'stopping', 36: 'stopping'}


class _Bad(Exception):
    pass


def _ip(raw):
    ip = (raw or '').strip()
    if not is_valid_ip(ip):
        raise _Bad('valid ip required')
    return ip


def _attr(obj, name, default=None):
    return getattr(obj, name, default) if obj is not None else default


def snapshot(conn):
    mx = conn.mixerstate
    service = mx.get('streaming-service')
    status = mx.get('streaming-status')
    stats = mx.get('streaming-stats')
    audio = mx.get('streaming-audio-bitrate')
    rec_status = mx.get('recording-status')
    rec_settings = mx.get('recording-settings')
    rec_disk = mx.get('recording-disk')
    rec_time = mx.get('recording-duration')
    has_stream = service is not None or status is not None
    has_record = rec_status is not None or rec_settings is not None
    out = {'has_streaming': has_stream, 'has_recording': has_record}
    if has_stream:
        code = _attr(status, 'status', -1)
        out['streaming'] = {
            'status': STREAM_STATUS.get(code, 'unknown'), 'status_code': code,
            'service': _attr(service, 'name', ''), 'url': _attr(service, 'url', ''),
            'key': _attr(service, 'key', ''),
            'bitrate_min': _attr(service, 'min'), 'bitrate_max': _attr(service, 'max'),
            'audio_min': _attr(audio, 'min'), 'audio_max': _attr(audio, 'max'),
            'bitrate': _attr(stats, 'bitrate'), 'cache': _attr(stats, 'cache'),
        }
    if has_record:
        out['recording'] = {
            'recording': bool(_attr(rec_status, 'is_recording', False)),
            'stopping': bool(_attr(rec_status, 'is_stopping', False)),
            'disk_full': bool(_attr(rec_status, 'disk_full', False)),
            'disk_error': bool(_attr(rec_status, 'disk_error', False)),
            'disk_unformatted': bool(_attr(rec_status, 'disk_unformatted', False)),
            'time_available': _attr(rec_status, 'time_available'),
            'filename': _attr(rec_settings, 'filename', ''),
            'disk1': _attr(rec_settings, 'disk1'), 'disk2': _attr(rec_settings, 'disk2'),
            'record_in_cameras': bool(_attr(rec_settings, 'record_in_cameras', False)),
            'disk': None if rec_disk is None else {
                'index': rec_disk.index, 'name': rec_disk.volumename,
                'time_available': rec_disk.time_available,
                'ready': bool(rec_disk.is_ready), 'attached': bool(rec_disk.is_attached)},
            'duration': None if rec_time is None else '%02d:%02d:%02d' % (
                rec_time.hours, rec_time.minutes, rec_time.seconds),
            'dropped_frames': bool(_attr(rec_time, 'has_dropped_frames', False)),
        }
    return out


def _conn_or_409(ip):
    return ATEMInstanceManager.peek_connection(ip)


def _log(ip, action, summary):
    try:
        from atem_control.activity import ActivityLog, record_activity
        record_activity(feature=ActivityLog.FEATURE_ATEM_CONTROL,
                        device=ActivityLog.DEVICE_ATEM, action=f'atem_{action}',
                        target=ip, summary=summary)
    except Exception:
        logger.exception('stream/record activity log failed')


@require_GET
@access_required
def stream_state(request):
    try:
        ip = _ip(request.GET.get('ip'))
    except _Bad as e:
        return HttpResponseBadRequest(str(e))
    conn = _conn_or_409(ip)
    if conn is None:
        return JsonResponse({'error': 'switcher not connected'}, status=409)
    return JsonResponse(snapshot(conn))


def _text(value, limit):
    value = str(value)
    if len(value.encode('utf-8')) >= limit:
        raise _Bad(f'too long (max {limit - 1} bytes)')
    return value


def _rate(value):
    number = int(value)
    if not 0 <= number <= 200_000_000:
        raise _Bad('bitrate out of range')
    return number


@require_POST
@access_required
def stream_action(request):
    """Body ``{ip, action, …}``; action is one of start_stream, stop_stream,
    start_record, stop_record, stream_settings, audio_bitrate,
    record_settings."""
    try:
        body = json.loads(request.body or b'{}')
        ip = _ip(body.get('ip'))
        action = body.get('action')
        conn = _conn_or_409(ip)
        if conn is None:
            return JsonResponse({'error': 'switcher not connected'}, status=409)
        if action == 'start_stream':
            streaming.start_streaming(conn)
            summary = 'Started streaming'
        elif action == 'stop_stream':
            streaming.stop_streaming(conn)
            summary = 'Stopped streaming'
        elif action == 'start_record':
            recording.start_recording(conn)
            summary = 'Started recording'
        elif action == 'stop_record':
            recording.stop_recording(conn)
            summary = 'Stopped recording'
        elif action == 'stream_settings':
            kwargs = {}
            for key, limit in (('name', 64), ('url', 512), ('key', 512)):
                if key in body:
                    kwargs[key] = _text(body[key], limit)
            if 'bitrate_min' in body or 'bitrate_max' in body:
                kwargs['bitrate_min'] = _rate(body['bitrate_min'])
                kwargs['bitrate_max'] = _rate(body['bitrate_max'])
            if not kwargs:
                raise _Bad('nothing to change')
            streaming.set_streaming_service(conn, **kwargs)
            summary = 'Changed streaming settings (' + ', '.join(sorted(kwargs)) + ')'
        elif action == 'audio_bitrate':
            streaming.set_streaming_audio_bitrate(conn, _rate(body['bitrate_min']), _rate(body['bitrate_max']))
            summary = 'Changed streaming audio bitrate'
        elif action == 'record_settings':
            kwargs = {}
            if 'filename' in body:
                kwargs['filename'] = _text(body['filename'], 128)
            for key in ('disk1', 'disk2'):
                if key in body:
                    kwargs[key] = -1 if body[key] in (None, '') else int(body[key])
            if 'record_in_camera' in body:
                kwargs['record_in_camera'] = bool(body['record_in_camera'])
            if not kwargs:
                raise _Bad('nothing to change')
            recording.set_recording_settings(conn, **kwargs)
            summary = 'Changed recording settings (' + ', '.join(sorted(kwargs)) + ')'
        else:
            raise _Bad('unknown action')
    except _Bad as e:
        return HttpResponseBadRequest(str(e))
    except (KeyError, TypeError, ValueError) as e:
        return HttpResponseBadRequest(f'bad request: {e}')
    _log(ip, action, summary)
    return JsonResponse({'ok': True})
