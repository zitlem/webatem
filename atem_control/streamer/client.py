"""A small synchronous client for the Blackmagic Streaming Encoder Ethernet
Protocol (Web Presenter HD/4K, Streaming Encoder HD/4K), TCP 9977.

The protocol is blocks of text: a ``HEADER:`` line, ``Key: Value`` lines,
a blank line. On connect the device dumps every block and ends with
``END PRELUDE:``. A write is a block holding only the keys to change; the
device answers ``ACK`` (or ``NACK``) and re-sends the changed block. Values
in ``Available …`` lists are comma separated, with ``\\`` escaping a comma,
backslash or any other character inside an item.

Same shape as ``videohubwire``: blocking, one socket, no thread; pushed
blocks are applied whenever the client reads.
"""
import logging
import socket
import time

logger = logging.getLogger(__name__)

PORT = 9977
QUIET_S = 0.05

# The blocks and keys a client may write (the protocol document's
# read/write column). Everything else is refused before it reaches the wire.
WRITABLE = {
    'STREAM SETTINGS': ('Current Platform', 'Current Server', 'Current Quality Level',
                        'Video Mode', 'Stream Key', 'Password', 'Current URL'),
    'IDENTITY': ('Label',),
    'AUDIO SETTINGS': ('Current Monitor Out Audio Source',),
    'UI SETTINGS': ('Current Locale', 'Current Audio Meter'),
}

STATUSES = ('Idle', 'Connecting', 'Streaming', 'Interrupted')


class StreamerError(Exception):
    pass


def split_list(value):
    """``a, b\\, c, d\\(e\\)`` -> ``['a', 'b, c', 'd(e)']``."""
    items, current, escaped = [], [], False
    for ch in value:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == '\\':
            escaped = True
        elif ch == ',':
            items.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = ''.join(current).strip()
    if tail or items:
        items.append(tail)
    return [i for i in items if i != '']


def unescape(value):
    out, escaped = [], False
    for ch in value:
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == '\\':
            escaped = True
        else:
            out.append(ch)
    return ''.join(out)


class Streamer:
    def __init__(self, host, port=PORT, *, connect_timeout=3.0, read_timeout=3.0,
                 socket_factory=None):
        self.host, self.port = host, port
        self.connect_timeout, self.read_timeout = connect_timeout, read_timeout
        self._factory = socket_factory or (lambda addr, timeout: socket.create_connection(addr, timeout))
        self._sock = None
        self._buf = b''
        self.blocks = {}          # header (no colon) -> {key: raw value}

    # ---- connection -----------------------------------------------------
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self._sock = self._factory((self.host, self.port), self.connect_timeout)
        self._sock.settimeout(self.read_timeout)
        self._buf = b''
        self.blocks = {}
        deadline = time.monotonic() + max(self.read_timeout, 5.0)
        while True:
            remaining = deadline - time.monotonic()
            block = self._recv_block(remaining if 'STREAM STATE' not in self.blocks else 0.3)
            if block is None:
                if 'STREAM STATE' in self.blocks or 'IDENTITY' in self.blocks:
                    return      # firmware without END PRELUDE: the dump went quiet
                raise StreamerError('no protocol preamble from the device')
            if self._apply(block) == 'END PRELUDE':
                return

    def close(self):
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ---- wire -----------------------------------------------------------
    def _send(self, text):
        if self._sock is None:
            raise StreamerError('not connected')
        self._sock.sendall(text.encode('utf-8'))

    def _recv_block(self, timeout):
        """Next block as a list of lines, or None if nothing arrives in time."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            # A block ends at a blank line; LF or CR LF.
            norm = self._buf.replace(b'\r\n', b'\n')
            if norm != self._buf:
                self._buf = norm
            while self._buf.startswith(b'\n'):
                self._buf = self._buf[1:]
            # ACK / NACK is a block of its own, with or without the blank
            # line before the echoed block that follows it.
            line_end = self._buf.find(b'\n')
            if line_end != -1 and self._buf[:line_end].strip() in (b'ACK', b'NACK', b'NAK'):
                raw, self._buf = self._buf[:line_end], self._buf[line_end + 1:]
                return [raw.decode('ascii').strip()]
            end = self._buf.find(b'\n\n')
            if end != -1:
                raw, self._buf = self._buf[:end], self._buf[end + 2:]
                return raw.decode('utf-8', 'replace').split('\n')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise StreamerError('device closed the connection')
            self._buf += chunk

    def _apply(self, lines):
        header = lines[0].strip()
        if header.endswith(':'):
            header = header[:-1]
        if header in ('ACK', 'NACK', 'NAK', 'END PRELUDE'):
            return header
        target = self.blocks.setdefault(header, {})
        for line in lines[1:]:
            key, sep, value = line.partition(':')
            if sep:
                target[key.strip()] = value.strip()
        return header

    def _drain(self, quiet=QUIET_S):
        while True:
            block = self._recv_block(quiet)
            if block is None:
                return
            self._apply(block)

    def _await_ack(self, what):
        deadline = time.monotonic() + self.read_timeout
        while True:
            block = self._recv_block(deadline - time.monotonic())
            if block is None:
                raise StreamerError(f'timed out waiting for ACK {what}')
            header = self._apply(block)
            if header == 'ACK':
                return
            if header in ('NACK', 'NAK'):
                raise StreamerError(f'device refused {what}')

    # ---- commands -------------------------------------------------------
    def set(self, block, values):
        """Write ``values`` (an ordered list of (key, value) or a dict) to
        ``block``. Only writable keys are sent; the echo is applied."""
        allowed = WRITABLE.get(block)
        if allowed is None:
            raise StreamerError(f'{block} is not writable')
        items = list(values.items()) if isinstance(values, dict) else list(values)
        if not items:
            return
        lines = []
        for key, value in items:
            if key not in allowed:
                raise StreamerError(f'{key} is not writable in {block}')
            value = str(value)
            if '\n' in value or '\r' in value:
                raise StreamerError(f'{key}: line breaks are not allowed')
            lines.append(f'{key}: {value}\n')
        self._send(f'{block}:\n' + ''.join(lines) + '\n')
        self._await_ack(f'{block} change')
        self._drain(0.15)       # the device re-sends the changed block

    def _action(self, block, action, what):
        self._send(f'{block}:\nAction: {action}\n\n')
        self._await_ack(what)
        self._drain(0.1)

    def start(self):
        self._action('STREAM STATE', 'Start', 'start streaming')

    def stop(self):
        self._action('STREAM STATE', 'Stop', 'stop streaming')

    def reboot(self):
        self._send('SHUTDOWN:\nAction: Reboot\n\n')
        try:
            self._await_ack('reboot')
        finally:
            self.close()

    def request(self, block):
        """Ask the device to re-send ``block`` (bitrate, duration and cache
        in STREAM STATE are only sent when asked)."""
        self._send(f'{block}:\n\n')
        self._await_ack(f'{block} request')
        self._drain()

    # ---- state ------------------------------------------------------------
    def state(self):
        self.request('STREAM STATE')
        return self.snapshot()

    def _lists(self, block):
        raw = self.blocks.get(block, {})
        return {k: (split_list(v) if k.startswith('Available') else unescape(v)) for k, v in raw.items()}

    def snapshot(self):
        interfaces = []
        for header in sorted(h for h in self.blocks if h.startswith('NETWORK INTERFACE')):
            b = self.blocks[header]
            interfaces.append({
                'name': b.get('Name', header), 'mac': b.get('MAC Address', ''),
                'dhcp': b.get('Dynamic IP', '').lower() == 'true',
                'addresses': split_list(b.get('Current Addresses', '')),
                'gateway': b.get('Current Gateway', ''),
                'dns': split_list(b.get('Current DNS Servers', '')),
                'priority': b.get('Priority', ''),
            })
        stream = self.blocks.get('STREAM STATE', {})
        status = stream.get('Status', '')

        def num(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return {
            'identity': dict(self.blocks.get('IDENTITY', {})),
            'version': dict(self.blocks.get('VERSION', {})),
            'protocol': self.blocks.get('PROTOCOL PREAMBLE', {}).get('Version', ''),
            'interfaces': interfaces,
            'settings': self._lists('STREAM SETTINGS'),
            'audio': self._lists('AUDIO SETTINGS'),
            'ui': self._lists('UI SETTINGS'),
            'stream': {
                'status': status if status in STATUSES else (status or 'Unknown'),
                'bitrate': num(stream.get('Bitrate')),
                'duration': stream.get('Duration', ''),
                'cache': num(stream.get('Cache Used')),
            },
        }
