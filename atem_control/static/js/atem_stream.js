/* ATEM built-in streaming / recording panel (local addition):
 * atemStreamPanel(), in templates/local/_header_extra.html. Hidden unless
 * the connected switcher reports streaming or recording state (Mini Pro /
 * Extreme, some Constellations); talks to /atem/stream/ over HTTP. */
(function () {
    'use strict';

    var IDLE_POLL_MS = 3000, OPEN_POLL_MS = 1000;

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
            return r.text().then(function (t) { var m = t; try { m = JSON.parse(t).error || t; } catch (e) { /* text */ } throw new Error(m); });
        });
    }

    window.atemStreamPanel = function () {
        return {
            open: false, available: false, busy: false, error: '', showKey: false,
            s: { has_streaming: false, has_recording: false, streaming: {}, recording: {} },
            f: {}, _timer: null, _inflight: false, _formFor: null,

            boot: function () {
                var self = this;
                this.schedule(IDLE_POLL_MS);
                this.$watch('open', function (v) { self.schedule(v ? OPEN_POLL_MS : IDLE_POLL_MS); if (v) { self.poll(); self.resetForm(); } });
            },

            ip: function () {
                var st = window.Alpine && window.Alpine.store('atem');
                return st && st.connected ? st.currentIP : '';
            },

            schedule: function (ms) {
                var self = this;
                if (this._timer) clearInterval(this._timer);
                this._timer = setInterval(function () { self.poll(); }, ms);
            },

            poll: function () {
                var self = this, ip = this.ip();
                if (!ip) { this.available = false; return; }
                if (this._inflight) return;
                this._inflight = true;
                fetch(window.LOCAL_PANEL_URLS.streamState + '?ip=' + encodeURIComponent(ip), { cache: 'no-store' })
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (snap) {
                        if (!snap) { self.available = false; return; }
                        self.s = Object.assign({ streaming: {}, recording: {} }, snap);
                        self.available = !!(snap.has_streaming || snap.has_recording);
                        if (self._formFor !== ip) { self._formFor = ip; self.resetForm(); }
                    })
                    .catch(function () { /* next poll */ })
                    .finally(function () { self._inflight = false; });
            },

            openPanel: function () { this.open = true; },

            onAir: function () {
                return (this.s.streaming && this.s.streaming.status === 'on_air') || (this.s.recording && this.s.recording.recording);
            },

            resetForm: function () {
                var st = this.s.streaming || {}, rec = this.s.recording || {};
                this.f = {
                    name: st.service || '', url: st.url || '', key: st.key || '',
                    vmin: st.bitrate_min ? st.bitrate_min / 1e6 : 0, vmax: st.bitrate_max ? st.bitrate_max / 1e6 : 0,
                    filename: rec.filename || ''
                };
            },

            streamText: function () {
                return ({ idle: 'IDLE', connecting: 'CONNECTING…', on_air: 'ON AIR', stopping: 'STOPPING…' })[this.s.streaming.status] || 'UNKNOWN';
            },

            recordText: function () {
                var r = this.s.recording;
                return r.recording ? 'RECORDING' : (r.stopping ? 'STOPPING…' : 'STOPPED');
            },

            mbps: function (b) { return (b / 1e6).toFixed(2) + ' Mb/s'; },

            hours: function (sec) {
                var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60);
                return (h ? h + 'h ' : '') + m + 'm';
            },

            act: function (action, question) {
                var self = this;
                if (question && !window.confirm(question)) return;
                this.busy = true;
                post(window.LOCAL_PANEL_URLS.streamAction, { ip: this.ip(), action: action })
                    .then(function () { self.error = ''; self.poll(); })
                    .catch(function (e) { self.error = e.message; })
                    .finally(function () { self.busy = false; });
            },

            saveStream: function () {
                var self = this, f = this.f;
                if (this.s.streaming.status === 'on_air' && !window.confirm('The switcher is streaming. Change the stream settings anyway?')) return;
                var body = { ip: this.ip(), action: 'stream_settings', name: f.name, url: f.url, key: f.key };
                if (f.vmin && f.vmax) { body.bitrate_min = Math.round(f.vmin * 1e6); body.bitrate_max = Math.round(f.vmax * 1e6); }
                this.busy = true;
                post(window.LOCAL_PANEL_URLS.streamAction, body)
                    .then(function () { self.error = ''; self.poll(); })
                    .catch(function (e) { self.error = e.message; })
                    .finally(function () { self.busy = false; });
            },

            saveRecord: function (changes) {
                var self = this;
                this.busy = true;
                post(window.LOCAL_PANEL_URLS.streamAction, Object.assign({ ip: this.ip(), action: 'record_settings' }, changes))
                    .then(function () { self.error = ''; self.poll(); })
                    .catch(function (e) { self.error = e.message; })
                    .finally(function () { self.busy = false; });
            }
        };
    };
})();
