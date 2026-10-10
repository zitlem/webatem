/* SuperSource panel (local addition): ssrcPanel(), the Alpine component in
 * templates/local/_header_extra.html and supersource/_panel.html.
 *
 * Not part of the esbuild bundle: it reads the switcher IP from the bundled
 * store and talks to /atem/supersource/ over HTTP, which rides the control
 * page's own ATEM session.
 *
 * Geometry: the program frame is 32 x 18 units, centre (0, 0), y up. Box
 * position is sent in 1/100 unit (x ±4800, y ±3400), size in 1/1000 of the
 * frame (70-1000), crop top/bottom in 1/1000 of 18 units, left/right of 32.
 */
(function () {
    'use strict';

    var IDLE_POLL_MS = 3000;    // is there a SuperSource at all?
    var OPEN_POLL_MS = 250;     // live box state while the panel is open
    var DRAG_SEND_MS = 40;      // same rate as WebATEM's sliders
    var HOLD_MS = 600;          // keep the local value this long after a release

    function csrf() {
        var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function post(url, data) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(data)
        }).then(function (r) {
            if (r.ok) return r.json();
            return r.text().then(function (t) {
                var msg = t;
                try { msg = JSON.parse(t).error || t; } catch (e) { /* plain text */ }
                throw new Error(msg);
            });
        });
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function atem() {
        return window.Alpine && window.Alpine.store('atem');
    }

    // Layout presets, in wire units; sources are kept as they are.
    var PRESETS = [
        { name: '2 × 2', boxes: [[true, -800, 450, 500], [true, 800, 450, 500], [true, -800, -450, 500], [true, 800, -450, 500]] },
        { name: 'Side by side', boxes: [[true, -800, 0, 500], [true, 800, 0, 500], [false], [false]] },
        { name: 'PiP', boxes: [[true, 0, 0, 1000], [true, 1020, 560, 300], [false], [false]] },
        { name: '1 + 3', boxes: [[true, -400, 0, 750], [true, 1200, 450, 250], [true, 1200, 0, 250], [true, 1200, -450, 250]] }
    ];

    window.ssrcPanel = function () {
        return {
            open: false, count: 0, current: 0, selected: 0, error: '',
            data: null, sources: [], presets: PRESETS,
            boxSliders: [
                { key: 'x', label: 'X', min: -4800, max: 4800, step: 1, div: 100, dp: 2 },
                { key: 'y', label: 'Y', min: -3400, max: 3400, step: 1, div: 100, dp: 2 },
                { key: 'size', label: 'Size', min: 70, max: 1000, step: 1, div: 1000, dp: 2 },
                { key: 'top', label: 'Crop top', min: 0, max: 18000, step: 10, div: 1000, dp: 2, crop: true },
                { key: 'bottom', label: 'Crop bottom', min: 0, max: 18000, step: 10, div: 1000, dp: 2, crop: true },
                { key: 'left', label: 'Crop left', min: 0, max: 32000, step: 10, div: 1000, dp: 2, crop: true },
                { key: 'right', label: 'Crop right', min: 0, max: 32000, step: 10, div: 1000, dp: 2, crop: true }
            ],
            artSliders: [{ key: 'clip', label: 'Clip' }, { key: 'gain', label: 'Gain' }],
            _timer: null, _inflight: false, _held: {}, _sendTimer: null, _pending: null, _drag: null,

            get ssrc() {
                return this.data && this.data.supersources ? this.data.supersources[this.current] || null : null;
            },

            boot: function () {
                var self = this;
                this.schedule(IDLE_POLL_MS);
                window.addEventListener('pointermove', function (e) { self.dragMove(e); });
                window.addEventListener('pointerup', function (e) { self.dragEnd(e); });
                this.$watch('open', function (v) { self.schedule(v ? OPEN_POLL_MS : IDLE_POLL_MS); if (v) self.poll(); });
            },

            ip: function () {
                var s = atem();
                return s && s.connected ? s.currentIP : '';
            },

            schedule: function (ms) {
                var self = this;
                if (this._timer) clearInterval(this._timer);
                this._timer = setInterval(function () { self.poll(); }, ms);
            },

            poll: function () {
                var self = this, ip = this.ip();
                if (!ip) { this.count = 0; return; }
                if (this._inflight || this._drag) return;
                this._inflight = true;
                fetch(window.LOCAL_PANEL_URLS.ssrcState + '?ip=' + encodeURIComponent(ip), { cache: 'no-store' })
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (snap) {
                        if (!snap) { self.count = 0; return; }
                        self.merge(snap);
                        self.error = '';
                    })
                    .catch(function () { /* next poll */ })
                    .finally(function () { self._inflight = false; });
            },

            // Keep a value the operator just set until the switcher's echo
            // has had time to arrive, so a box does not jump back mid-drag.
            merge: function (snap) {
                var now = Date.now(), held = this._held;
                (snap.supersources || []).forEach(function (s) {
                    s.boxes.forEach(function (b) {
                        Object.keys(b).forEach(function (k) {
                            var h = held[s.index + ':' + b.box + ':' + k];
                            if (h && h.until > now) b[k] = h.value;
                        });
                    });
                    if (s.art) Object.keys(s.art).forEach(function (k) {
                        var h = held[s.index + ':art:' + k];
                        if (h && h.until > now) s.art[k] = h.value;
                    });
                });
                this.data = snap;
                this.sources = snap.sources || [];
                this.count = (snap.supersources || []).length;
                if (this.current >= this.count) this.current = 0;
            },

            openPanel: function () {
                this.open = true;
            },

            boxes: function () {
                return this.ssrc ? this.ssrc.boxes : [];
            },

            box: function () {
                if (this.selected === 'art' || !this.ssrc) return null;
                var b = this.ssrc.boxes[this.selected];
                return b && b.known ? b : null;
            },

            sourceName: function (id) {
                if (id === null || id === undefined) return '—';
                for (var i = 0; i < this.sources.length; i++) {
                    if (this.sources[i].source === id) return this.sources[i].short || this.sources[i].long;
                }
                return String(id);
            },

            boxStyle: function (b) {
                var w = b.size / 10;                      // % of frame width and height
                var left = 50 + b.x / 32 - w / 2;         // x: 3200 wire units = 100%
                var top = 50 - b.y / 18 - w / 2;          // y: 1800 wire units = 100%
                var clip = b.masked
                    ? 'inset(' + (b.top / 180) + '% ' + (b.right / 320) + '% ' + (b.bottom / 180) + '% ' + (b.left / 320) + '%)'
                    : 'none';
                return 'left:' + left + '%;top:' + top + '%;width:' + w + '%;height:' + w + '%;clip-path:' + clip +
                    ';z-index:' + (10 - b.box);
            },

            hold: function (key, value) {
                this._held[key] = { value: value, until: Date.now() + HOLD_MS };
            },

            // ---- writes -----------------------------------------------------
            sendBox: function (props, drag) {
                var self = this, b = this.box();
                if (!b) return;
                var ip = this.ip();
                Object.keys(props).forEach(function (k) {
                    b[k] = props[k];
                    self.hold(self.current + ':' + b.box + ':' + k, props[k]);
                });
                return post(window.LOCAL_PANEL_URLS.ssrcBox, { ip: ip, ssrc: this.current, box: b.box, props: props, drag: !!drag })
                    .catch(function (e) { self.error = e.message; });
            },

            setBox: function (props) { this.sendBox(props, false); },

            // A slider sends at most every DRAG_SEND_MS while it moves, then
            // its final value once.
            throttled: function (fn) {
                var self = this;
                this._pending = fn;
                if (this._sendTimer) return;
                this._sendTimer = setTimeout(function () {
                    self._sendTimer = null;
                    var f = self._pending; self._pending = null;
                    if (f) f();
                }, DRAG_SEND_MS);
            },

            slide: function (key, value) {
                var self = this, props = {}; props[key] = value;
                var b = this.box(); if (b) b[key] = value;
                this.throttled(function () { self.sendBox(props, true); });
            },

            slideEnd: function (key, value) {
                var props = {}; props[key] = value;
                this._pending = null;
                this.sendBox(props, false);
            },

            setArt: function (props) { this.sendArt(props, false); },

            sendArt: function (props, drag) {
                var self = this, s = this.ssrc;
                if (!s || !s.art) return;
                Object.keys(props).forEach(function (k) {
                    s.art[k] = props[k];
                    self.hold(self.current + ':art:' + k, props[k]);
                });
                return post(window.LOCAL_PANEL_URLS.ssrcArt, { ip: this.ip(), ssrc: this.current, props: props, drag: !!drag })
                    .catch(function (e) { self.error = e.message; });
            },

            slideArt: function (key, value) {
                var self = this, props = {}; props[key] = value;
                if (this.ssrc && this.ssrc.art) this.ssrc.art[key] = value;
                this.throttled(function () { self.sendArt(props, true); });
            },

            slideArtEnd: function (key, value) {
                var props = {}; props[key] = value;
                this._pending = null;
                this.sendArt(props, false);
            },

            applyPreset: function (preset) {
                var self = this, s = this.ssrc;
                if (!s) return;
                var items = preset.boxes.map(function (spec, i) {
                    var props = spec[0] ? { enabled: true, x: spec[1], y: spec[2], size: spec[3], masked: false }
                                        : { enabled: false };
                    var b = s.boxes[i];
                    if (b) Object.keys(props).forEach(function (k) { b[k] = props[k]; self.hold(self.current + ':' + i + ':' + k, props[k]); });
                    return { box: i, props: props };
                });
                post(window.LOCAL_PANEL_URLS.ssrcBox, { ip: this.ip(), ssrc: this.current, boxes: items })
                    .catch(function (e) { self.error = e.message; });
            },

            // ---- dragging on the frame ----------------------------------------
            dragStart: function (e, b, mode) {
                if (!b.known) return;
                e.preventDefault();
                this.selected = b.box;
                var rect = this.$refs.frame.getBoundingClientRect();
                this._drag = { mode: mode, box: b, startX: e.clientX, startY: e.clientY, w: rect.width, h: rect.height,
                               x: b.x, y: b.y, size: b.size };
            },

            dragMove: function (e) {
                var d = this._drag;
                if (!d) return;
                var dx = e.clientX - d.startX, dy = e.clientY - d.startY, props;
                if (d.mode === 'move') {
                    props = { x: Math.round(clamp(d.x + dx / d.w * 3200, -4800, 4800)),
                              y: Math.round(clamp(d.y - dy / d.h * 1800, -3400, 3400)) };
                } else {
                    // The box grows about its centre: a corner moved by dx widens
                    // it by 2·dx.
                    var grow = (dx / d.w + dy / d.h) * 1000;
                    props = { size: Math.round(clamp(d.size + grow, 70, 1000)) };
                }
                var self = this;
                Object.keys(props).forEach(function (k) { d.box[k] = props[k]; });
                d.last = props;
                this.throttled(function () { self.sendBox(props, true); });
            },

            dragEnd: function () {
                var d = this._drag;
                if (!d) return;
                this._drag = null;
                this._pending = null;
                if (d.last) this.sendBox(d.last, false);
            }
        };
    };
})();
