"""``videohubwire.Videohub`` plus locks, salvos and take mode.

The library parses CONFIGURATION / TAKE MODE and drops them, routes one
crosspoint per command and never writes locks. ``Hub`` adds those on the
library's own framing (``_send`` / ``_recv_block`` / ``_apply_block``), so
pushed updates that arrive while waiting for an ACK are still applied.
Protocol reference: Blackmagic Videohub Ethernet Protocol v2.8.
"""
import time

from videohubwire import Videohub, VideohubError

# Lock requests: O = take the lock for this connection, U = release ours,
# F = force-release someone else's (the hub then reports U).
LOCK_MODES = {'lock': 'O', 'unlock': 'U', 'force': 'F'}


def _flag(value):
    return str(value).strip().lower() == 'true'


class Hub(Videohub):
    """A Videohub connection that also tracks take mode and writes locks."""

    def __init__(self, *args, **kwargs):
        self.take_mode = {}      # output index -> bool (hub's per-output setting)
        self.configuration = {}  # CONFIGURATION block, lower-case keys
        super().__init__(*args, **kwargs)

    def _apply_block(self, lines):
        header = lines[0].strip()
        body = [ln for ln in lines[1:] if ln.strip()]
        if header == 'TAKE MODE:':
            self._apply_indexed(body, self.take_mode, _flag)
            return header
        if header == 'CONFIGURATION:':
            for key, val in self._kv(body):
                self.configuration[key] = val
            return header
        return super()._apply_block(lines)

    def _await_ack(self, what):
        """Wait for this command's ACK/NAK, applying interleaved pushes."""
        deadline = time.monotonic() + self.read_timeout
        while True:
            block = self._recv_block(deadline - time.monotonic())
            if block is None:
                raise VideohubError(f'timed out waiting for ACK {what}')
            header = block[0].strip()
            if header == 'ACK':
                return
            if header == 'NAK':
                raise VideohubError(f'hub refused {what}')
            self._apply_block(block)

    def _check_output(self, dest):
        dest = int(dest)
        if dest < 0 or (self.video_outputs and dest >= self.video_outputs):
            raise VideohubError(f'output {dest} outside this hub')
        return dest

    def route_many(self, routes):
        """Route several crosspoints in one ``VIDEO OUTPUT ROUTING`` block
        (a salvo), atomically from the hub's point of view."""
        pairs = []
        for dest, src in routes:
            dest, src = self._check_output(dest), int(src)
            if src < 0 or (self.video_inputs and src >= self.video_inputs):
                raise VideohubError(f'input {src} outside this hub')
            pairs.append((dest, src))
        if not pairs:
            return
        lines = ''.join(f'{d} {s}\n' for d, s in pairs)
        self._send(f'VIDEO OUTPUT ROUTING:\n{lines}\n')
        self._await_ack('routing ' + ', '.join(f'{d}<-{s}' for d, s in pairs))
        for dest, src in pairs:
            self.routing[dest] = src

    def set_lock(self, dest, mode):
        """``mode``: 'lock', 'unlock' or 'force' (release another client's)."""
        dest = self._check_output(dest)
        code = LOCK_MODES[mode]
        self._send(f'VIDEO OUTPUT LOCKS:\n{dest} {code}\n\n')
        self._await_ack(f'{mode} on output {dest}')
        self.locks[dest] = 'O' if code == 'O' else 'U'

    def state(self):
        snap = super().state()
        snap['device']['unique_id'] = self.device.get('unique id', '')
        snap['device']['take_mode'] = _flag(self.configuration.get('take mode', 'false'))
        for out in snap['outputs']:
            out['take_mode'] = bool(self.take_mode.get(out['index'], False))
        return snap
