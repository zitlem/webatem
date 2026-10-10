"""One shared connection per device, closed as soon as nobody is watching
(local addition, used by the Videohub and streaming-encoder pages).

Every open page polls the device about once a second and names itself with
a random viewer id. A device stays connected while any viewer polled it in
the last ``IDLE_SECONDS``; a page leaving (its ← button, closing the tab)
releases its viewer, and the connection closes at once when no other viewer
is active. A reaper thread closes devices whose viewers all vanished
without saying so (a crashed browser, a dropped network).

Devices take only a few client sessions each, and some (Videohub locks) tie
state to the session, so a session nobody uses is closed rather than kept.
"""
import atexit
import logging
import threading
import time

logger = logging.getLogger(__name__)

IDLE_SECONDS = 30.0        # no poll from any viewer for this long: close
RELEASE_GRACE_SECONDS = 5.0  # another viewer polled this recently: keep it open
REAP_EVERY_SECONDS = 15.0


class DevicePool:
    """``connect(ip)`` opens a device; ``lost(exc)`` says whether an
    exception means the cached socket is dead (reconnect once) rather than
    the device's answer."""

    def __init__(self, name, connect, lost, clock=time.monotonic, start_reaper=True):
        self.name = name
        self._connect = connect
        self._lost = lost
        self._clock = clock
        self._devices = {}     # ip -> device
        self._locks = {}       # ip -> threading.Lock (one command at a time)
        self._viewers = {}     # ip -> {viewer id: last poll time}
        self._used = {}        # ip -> last use, for calls without a viewer
        self._registry = threading.Lock()
        self._reaper = None
        self._start_reaper = start_reaper
        atexit.register(self.close_all)

    # ---- bookkeeping --------------------------------------------------------
    def _lock_for(self, ip):
        with self._registry:
            lock = self._locks.get(ip)
            if lock is None:
                lock = self._locks[ip] = threading.Lock()
            return lock

    def _ensure_reaper(self):
        if self._reaper is not None or not self._start_reaper:
            return
        with self._registry:
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._reap_forever, daemon=True,
                                                name=f'{self.name}-reaper')
                self._reaper.start()

    def _drop(self, ip, why):
        dev = self._devices.pop(ip, None)
        if dev is not None:
            logger.info('%s %s: closing session (%s)', self.name, ip, why)
            try:
                dev.close()
            except Exception:
                pass

    def _last_activity(self, ip, exclude=None):
        times = [t for v, t in self._viewers.get(ip, {}).items() if v != exclude]
        times.append(self._used.get(ip, 0.0))
        return max(times)

    def connected(self, ip):
        return ip in self._devices

    # ---- use ------------------------------------------------------------------
    def run(self, ip, fn, viewer=None):
        """Run ``fn(device)`` on a connected device under its lock,
        reconnecting once when the cached socket went stale."""
        self._ensure_reaper()
        with self._lock_for(ip):
            now = self._clock()
            if viewer:
                self._viewers.setdefault(ip, {})[viewer] = now
            else:
                self._used[ip] = now
            last_exc = None
            for _attempt in (1, 2):
                dev = self._devices.get(ip)
                if dev is None:
                    dev = self._connect(ip)
                    self._devices[ip] = dev
                try:
                    return fn(dev)
                except Exception as e:
                    if not (isinstance(e, OSError) or self._lost(e)):
                        raise
                    logger.warning('%s %s: connection lost (%s); reconnecting', self.name, ip, e)
                    self._drop(ip, 'connection lost')
                    last_exc = e
            raise last_exc

    def release(self, ip, viewer):
        """A page left. Close the session unless another viewer is active."""
        with self._lock_for(ip):
            viewers = self._viewers.get(ip, {})
            viewers.pop(viewer, None)
            if self._clock() - self._last_activity(ip) > RELEASE_GRACE_SECONDS:
                self._viewers.pop(ip, None)
                self._used.pop(ip, None)
                self._drop(ip, 'last viewer left')
                return True
            return False

    def reap(self):
        """Close devices nobody has polled for ``IDLE_SECONDS``."""
        now = self._clock()
        with self._registry:
            ips = list(self._devices)
        for ip in ips:
            lock = self._lock_for(ip)
            if not lock.acquire(blocking=False):
                continue      # in use right now
            try:
                if now - self._last_activity(ip) > IDLE_SECONDS:
                    self._viewers.pop(ip, None)
                    self._used.pop(ip, None)
                    self._drop(ip, f'idle {IDLE_SECONDS:.0f}s')
            finally:
                lock.release()

    def _reap_forever(self):
        while True:
            time.sleep(REAP_EVERY_SECONDS)
            try:
                self.reap()
            except Exception:
                logger.exception('%s reaper failed', self.name)

    def forget(self, ip):
        with self._lock_for(ip):
            self._viewers.pop(ip, None)
            self._drop(ip, 'forgotten')

    def close_all(self):
        with self._registry:
            ips = list(self._devices)
        for ip in ips:
            self._drop(ip, 'exit')
