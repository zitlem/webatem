/* Streaming-encoder page (local addition): the Alpine component behind
 * templates/streamer/control.html.
 *
 * Shows what the device reports (polled once a second); a change is POSTed
 * and the device's acknowledged state comes back in the answer. Changing the
 * platform is sent at once, because the device then offers that platform's
 * servers and quality levels; the other stream settings wait for Save and
 * go in one block.
 */
(function () {
    'use strict';

    var POLL_MS = 1000;

    function csrf() {
        var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    // This page's id: sent with every poll and action so the server keeps the
    // device's session open while the page watches, and closes it when the
    // page leaves (← or closing the tab) and no other page is watching.
    var VIEWER = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
        : 'v' + Date.now().toString(36) + Math.random().toString(36).slice(2);

    function releaseUrl(urls) { return urls.release; }

    function release(urls, ip) {
        if (!ip) return;
        try {
            fetch(releaseUrl(urls), {
                method: 'POST', keepalive: true,
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify({ ip: ip, viewer: VIEWER })
            });
        } catch (e) { /* leaving anyway; the server's idle reaper closes it */ }
    }

    function post(url, data) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(Object.assign({ viewer: VIEWER }, data))
        }).then(function (resp) {
            return resp.text().then(function (text) {
                var body;
                try { body = JSON.parse(text); } catch (e) { body = { error: text }; }
                if (!resp.ok) throw new Error((body && body.error) || ('HTTP ' + resp.status));
                return body;
            });
        });
    }

    // Form field -> STREAM SETTINGS key.
    var FIELDS = {
        platform: 'Current Platform', server: 'Current Server', quality: 'Current Quality Level',
        videoMode: 'Video Mode', url: 'Current URL', key: 'Stream Key', password: 'Password'
    };

    window.streamerPage = function (ip) {
        return {
            ip: ip, ready: false, loading: true, ok: false, error: '', busy: false, menu: false,
            identity: {}, version: {}, interfaces: [], settings: {}, audio: {}, ui: {},
            stream: { status: 'Unknown', bitrate: null, duration: '', cache: null },
            form: {}, saved: {}, device: { label: '' }, showKey: false,
            toasts: [], _toastId: 0, _poll: null, _polling: false,

            init: function () {
                var self = this;
                window.addEventListener('pagehide', function () { release(window.STREAMER_URLS, self.ip); });
                if (!this.ip) { this.loading = false; return; }
                this.open();
                document.addEventListener('visibilitychange', function () {
                    if (document.hidden) self.stopPoll(); else if (self.ready) self.startPoll();
                });
            },

            // The ← button: release this page's hold on the device, then go to
            // the Connect page (pagehide releases too; once is enough).
            leave: function () {
                this.stopPoll();
                release(window.STREAMER_URLS, this.ip);
                this.ip = '';
                window.location.href = window.STREAMER_URLS.connect;
            },

            open: function () {
                var self = this;
                this.loading = true;
                post(window.STREAMER_URLS.open, { ip: this.ip }).then(function (snap) {
                    self.apply(snap, true);
                    self.ready = true;
                    self.startPoll();
                    document.title = (snap.identity.Label || 'Streaming encoder') + ' · webATEM';
                }).catch(function (e) { self.error = e.message; self.ok = false; })
                  .finally(function () { self.loading = false; });
            },

            apply: function (snap, resetForm) {
                var wasDirty = this.dirty();
                this.identity = snap.identity || {};
                this.version = snap.version || {};
                this.interfaces = snap.interfaces || [];
                this.settings = snap.settings || {};
                this.audio = snap.audio || {};
                this.ui = snap.ui || {};
                this.stream = snap.stream || this.stream;
                var saved = {};
                for (var f in FIELDS) saved[f] = this.settings[FIELDS[f]] || '';
                this.saved = saved;
                if (resetForm || !wasDirty) this.form = Object.assign({}, saved);
                if (resetForm || this.device.label === undefined) this.device.label = this.identity.Label || '';
                this.ok = true;
                this.error = '';
            },

            startPoll: function () {
                var self = this;
                this.stopPoll();
                this._poll = setInterval(function () { self.poll(); }, POLL_MS);
            },

            stopPoll: function () {
                if (this._poll) clearInterval(this._poll);
                this._poll = null;
            },

            poll: function () {
                var self = this;
                if (this._polling || this.busy) return;
                this._polling = true;
                fetch(window.STREAMER_URLS.state + '?ip=' + encodeURIComponent(this.ip) + '&viewer=' + VIEWER, { cache: 'no-store' })
                    .then(function (r) { return r.json().then(function (b) { if (!r.ok) throw new Error(b.error || 'HTTP ' + r.status); return b; }); })
                    .then(function (snap) { self.apply(snap, false); })
                    .catch(function (e) { self.ok = false; self.error = e.message; })
                    .finally(function () { self._polling = false; });
            },

            // ---- display ----------------------------------------------------
            live: function () {
                return this.stream.status === 'Streaming' || this.stream.status === 'Connecting' ||
                    this.stream.status === 'Interrupted';
            },
            statusKey: function () {
                return ({ Idle: 'idle', Connecting: 'connecting', Streaming: 'live', Interrupted: 'interrupted' })[this.stream.status] || 'unknown';
            },
            statusText: function () {
                return ({ Idle: 'IDLE', Connecting: 'CONNECTING…', Streaming: 'ON AIR', Interrupted: 'INTERRUPTED' })[this.stream.status] || 'UNKNOWN';
            },
            duration: function () {
                var d = this.stream.duration || '';
                var parts = d.split(':');
                if (parts.length !== 4) return d || '—';
                var days = parseInt(parts[0], 10);
                return (days ? days + 'd ' : '') + parts.slice(1).join(':');
            },
            bitrate: function () {
                var b = this.stream.bitrate;
                if (b === null || b === undefined) return '—';
                return (b / 1e6).toFixed(b >= 1e7 ? 1 : 2) + ' Mb/s';
            },
            targetText: function () {
                var s = this.settings;
                return [s['Current Platform'], s['Current Server'], s['Current Quality Level'], s['Video Mode']]
                    .filter(Boolean).join(' · ');
            },
            versionText: function () {
                var v = this.version;
                return [this.identity.Model, v['Software Release'] ? 'software ' + v['Software Release'] : '',
                        this.identity['Unique ID'] ? 'ID ' + this.identity['Unique ID'] : ''].filter(Boolean).join(' · ');
            },
            list: function (key) {
                var v = this.settings[key];
                var items = Array.isArray(v) ? v.slice() : [];
                var current = { 'Available Servers': this.form.server, 'Available Quality Levels': this.form.quality,
                                'Available Video Modes': this.form.videoMode }[key];
                if (current && items.indexOf(current) === -1) items.unshift(current);
                return items;
            },
            platforms: function () {
                var a = this.settings['Available Default Platforms'] || [];
                var b = this.settings['Available Custom Platforms'] || [];
                var items = a.concat(b);
                if (this.form.platform && items.indexOf(this.form.platform) === -1) items.unshift(this.form.platform);
                return items;
            },
            audioList: function (key) { var v = this.audio[key]; return Array.isArray(v) ? v : []; },
            uiList: function (key) { var v = this.ui[key]; return Array.isArray(v) ? v : []; },

            dirty: function () {
                for (var f in FIELDS) if ((this.form[f] || '') !== (this.saved[f] || '')) return true;
                return false;
            },

            // ---- actions ----------------------------------------------------
            send: function (url, data, okText) {
                var self = this;
                this.busy = true;
                return post(url, Object.assign({ ip: this.ip }, data))
                    .then(function (snap) { self.apply(snap, false); if (okText) self.toast(okText, 'ok'); return snap; })
                    .catch(function (e) { self.toast(e.message, 'error'); throw e; })
                    .finally(function () { self.busy = false; });
            },

            startStream: function () {
                var target = this.targetText();
                if (!window.confirm('Go live now?' + (target ? '\n\n' + target : ''))) return;
                this.send(window.STREAMER_URLS.stream, { action: 'start' }).catch(function () {});
            },

            stopStream: function () {
                if (!window.confirm('Stop the stream? Viewers lose the picture.')) return;
                this.send(window.STREAMER_URLS.stream, { action: 'stop' }).catch(function () {});
            },

            liveGuard: function () {
                return !this.live() || window.confirm('The encoder is streaming. Change its settings anyway?');
            },

            changePlatform: function () {
                var self = this, value = this.form.platform;
                if (value === this.saved.platform) return;
                if (!this.liveGuard()) { this.form.platform = this.saved.platform; return; }
                this.send(window.STREAMER_URLS.settings, { block: 'STREAM SETTINGS', values: [['Current Platform', value]] })
                    .then(function () {
                        // The device picked its own server and quality for the new
                        // platform: show those rather than the old ones.
                        self.form.platform = self.saved.platform;
                        self.form.server = self.saved.server;
                        self.form.quality = self.saved.quality;
                    })
                    .catch(function () { self.form.platform = self.saved.platform; });
            },

            saveStream: function () {
                var self = this, values = [];
                for (var f in FIELDS) {
                    if (f === 'platform') continue;
                    if ((this.form[f] || '') !== (this.saved[f] || '')) values.push([FIELDS[f], this.form[f] || '']);
                }
                if (!values.length || !this.liveGuard()) return;
                this.send(window.STREAMER_URLS.settings, { block: 'STREAM SETTINGS', values: values }, 'Stream settings saved.')
                    .then(function () { self.form = Object.assign({}, self.saved); })
                    .catch(function () {});
            },

            resetForm: function () {
                this.form = Object.assign({}, this.saved);
            },

            saveSetting: function (block, key, value) {
                var self = this;
                this.send(window.STREAMER_URLS.settings, { block: block, values: [[key, value]] }, 'Saved.')
                    .then(function () { if (key === 'Label') self.device.label = self.identity.Label || ''; })
                    .catch(function () {});
            },

            reboot: function () {
                var self = this;
                var warn = this.live() ? '\n\nIt is streaming now: the stream will drop.' : '';
                if (!window.confirm('Reboot ' + (this.identity.Label || this.ip) + '?' + warn)) return;
                this.busy = true;
                post(window.STREAMER_URLS.reboot, { ip: this.ip })
                    .then(function () { self.toast('Rebooting… the page reconnects when it is back.', 'warn'); self.ok = false; })
                    .catch(function (e) { self.toast(e.message, 'error'); })
                    .finally(function () { self.busy = false; });
            },

            toast: function (text, kind) {
                var self = this, id = ++this._toastId;
                this.toasts.push({ id: id, text: text, kind: kind || 'info' });
                setTimeout(function () { self.toasts = self.toasts.filter(function (t) { return t.id !== id; }); },
                           kind === 'error' ? 6000 : 3500);
            }
        };
    };
})();
