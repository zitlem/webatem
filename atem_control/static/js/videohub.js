/* Videohub page (local addition): the Alpine component behind
 * templates/videohub/control.html.
 *
 * The page shows only what the hub reports: a route, lock or label change is
 * POSTed, and the hub's acknowledged state comes back in the answer and from
 * the ~750 ms state poll (which also picks up other panels' changes).
 *
 * Routing follows Blackmagic's Videohub Control and Smart Control panels:
 * pick a destination, then a source. With "Use TAKE" on, or on an output the
 * hub itself has in take mode, the route waits: TAKE (Enter) sends it,
 * CLEAR (Esc) drops it. Keyboard: ←/→ step the destination, ↑/↓ step the
 * source (always as a pending route, so stepping never puts anything on air
 * by itself), Enter takes, Esc clears.
 */
(function () {
    'use strict';

    var POLL_MS = 750;
    var LONG_PRESS_MS = 600;
    var STORE_VIEW = 'webatem-videohub-view';
    var STORE_TAKE = 'webatem-videohub-take';

    function csrf() {
        var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function getPref(key, fallback) {
        try {
            var v = localStorage.getItem(key);
            return v === null ? fallback : v;
        } catch (e) { return fallback; }
    }

    function setPref(key, value) {
        try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
    }

    function errorText(resp, body) {
        if (body && body.error) return body.error;
        return 'HTTP ' + resp.status;
    }

    function post(url, data, method) {
        return fetch(url, {
            method: method || 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(data)
        }).then(function (resp) {
            return resp.text().then(function (text) {
                var body = null;
                try { body = JSON.parse(text); } catch (e) { body = { error: text }; }
                if (!resp.ok) throw new Error(errorText(resp, body));
                return body;
            });
        });
    }

    function matches(item, filter) {
        if (!filter) return true;
        var f = filter.trim().toLowerCase();
        return item.label.toLowerCase().indexOf(f) !== -1 || String(item.index + 1) === f;
    }

    window.videohubPage = function (ip) {
        return {
            ip: ip,
            ready: false,
            loading: true,
            ok: false,
            error: '',
            device: {},
            inputs: [],
            outputs: [],
            previousRoutes: {},
            selected: 0,
            pending: null,          // {routes: [[dest, src], ...], name?}
            view: getPref(STORE_VIEW, 'buttons'),
            useTake: getPref(STORE_TAKE, '0') === '1',
            editLabels: false,
            destFilter: '',
            srcFilter: '',
            hover: null,
            salvos: [],
            salvoMenu: false,
            fileMenu: false,
            dialog: null,
            dialogValue: '',
            toasts: [],
            busy: false,
            _poll: null,
            _press: null,
            _toastId: 0,

            init: function () {
                var self = this;
                var asked = new URLSearchParams(location.search).get('view');
                if (asked === 'buttons' || asked === 'matrix') this.view = asked;   // ?view= for a bookmark
                if (!this.ip) { this.loading = false; return; }
                this.open();
                document.addEventListener('visibilitychange', function () {
                    if (document.hidden) self.stopPoll(); else if (self.ready) self.startPoll();
                });
                window.addEventListener('resize', function () { self.queueFit(); });
                this.$watch('view', function () { self.queueFit(); });
                this.$watch('destFilter', function () { self.queueFit(); });
                this.$watch('srcFilter', function () { self.queueFit(); });
            },

            // ---- state ------------------------------------------------------
            open: function () {
                var self = this;
                this.loading = true;
                this.error = '';
                post(window.VIDEOHUB_URLS.open, { ip: this.ip }).then(function (snap) {
                    self.apply(snap);
                    self.ready = true;
                    self.$nextTick(function () { self.queueFit(); });   // sized once it is visible
                    self.startPoll();
                    self.loadSalvos();
                    document.title = (snap.device.friendly_name || 'Videohub') + ' · webATEM';
                }).catch(function (e) {
                    self.error = e.message;
                    self.ok = false;
                }).finally(function () {
                    self.loading = false;
                });
            },

            apply: function (snap) {
                var changedShape = snap.inputs.length !== this.inputs.length ||
                    snap.outputs.length !== this.outputs.length;
                this.device = snap.device || {};
                this.inputs = snap.inputs || [];
                this.outputs = snap.outputs || [];
                this.previousRoutes = snap.previous || {};
                if (this.selected >= this.outputs.length) this.selected = 0;
                this.ok = true;
                this.error = '';
                if (changedShape) this.queueFit();
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
                fetch(window.VIDEOHUB_URLS.state + '?ip=' + encodeURIComponent(this.ip), { cache: 'no-store' })
                    .then(function (resp) {
                        return resp.json().then(function (body) {
                            if (!resp.ok) throw new Error(errorText(resp, body));
                            return body;
                        });
                    })
                    .then(function (snap) { self.apply(snap); })
                    .catch(function (e) { self.ok = false; self.error = e.message; })
                    .finally(function () { self._polling = false; });
            },

            // ---- lookups ----------------------------------------------------
            get dest() {
                return this.outputs[this.selected] || null;
            },

            modelText: function () {
                var model = (this.device.model_name || '').replace(/^Blackmagic /, '');
                return model && model !== this.device.friendly_name ? '· ' + model : '';
            },

            sourceLabel: function (index) {
                if (index === null || index === undefined) return '—';
                var input = this.inputs[index];
                return input ? input.label : 'Input ' + (index + 1);
            },

            previousFor: function (out) {
                var v = this.previousRoutes[String(out.index)];
                return v === undefined ? null : v;
            },

            filteredOutputs: function () {
                var f = this.destFilter;
                return this.outputs.filter(function (o) { return matches(o, f); });
            },

            filteredInputs: function () {
                var f = this.srcFilter;
                return this.inputs.filter(function (i) { return matches(i, f); });
            },

            needsTake: function (outIndex) {
                var out = this.outputs[outIndex];
                return this.useTake || !!(out && out.take_mode);
            },

            pendingText: function () {
                var p = this.pending;
                if (!p) return '';
                if (p.name) return 'Salvo ' + p.name + ' (' + p.routes.length + ' routes)';
                var r = p.routes[0];
                return this.sourceLabel(r[1]) + ' → ' + this.outputs[r[0]].label;
            },

            lockTitle: function () {
                var d = this.dest;
                if (!d) return '';
                if (d.lock === 'L') return 'Locked by another panel: force it unlocked';
                if (d.lock === 'O') return 'Release WebATEM\'s lock (double-click the destination also works)';
                return 'Lock this destination so nothing can route it (double-click or long-press also works)';
            },

            // ---- interaction ------------------------------------------------
            setView: function (view) {
                this.view = view;
                setPref(STORE_VIEW, view);
            },

            toggleTake: function () {
                this.useTake = !this.useTake;
                setPref(STORE_TAKE, this.useTake ? '1' : '0');
                if (!this.useTake) this.pending = null;
            },

            clickDest: function (out) {
                if (this.editLabels) { this.rename('output', out); return; }
                this.selected = out.index;
                if (this.pending && !this.pending.name) this.pending = null;
                this.revealSource();
            },

            dblDest: function (out) {
                if (this.editLabels) return;
                this.selected = out.index;
                if (out.lock === 'L') { this.toast('Locked by another panel. Use Force unlock.', 'warn'); return; }
                this.sendLock(out, out.lock === 'O' ? 'unlock' : 'lock');
            },

            pressStart: function (out) {
                var self = this;
                this.pressEnd();
                if (this.editLabels) return;
                this._press = setTimeout(function () {
                    self._press = null;
                    self.dblDest(out);
                }, LONG_PRESS_MS);
            },

            pressEnd: function () {
                if (this._press) clearTimeout(this._press);
                this._press = null;
            },

            clickSource: function (input) {
                if (this.editLabels) { this.rename('input', input); return; }
                this.queueOrRoute(this.selected, input.index);
            },

            clickCell: function (out, input) {
                if (this.editLabels) return;
                this.selected = out.index;
                this.queueOrRoute(out.index, input.index);
            },

            queueOrRoute: function (destIndex, srcIndex) {
                var out = this.outputs[destIndex];
                if (!out) return;
                if (out.lock === 'L') {
                    this.toast(out.label + ' is locked by another panel.', 'warn');
                    return;
                }
                if (this.needsTake(destIndex)) {
                    if (out.source === srcIndex) { this.pending = null; return; }   // clicking the live source cancels
                    this.pending = { routes: [[destIndex, srcIndex]] };
                    return;
                }
                if (out.source === srcIndex) return;
                this.sendRoutes([[destIndex, srcIndex]]);
            },

            take: function () {
                if (!this.pending) return;
                var routes = this.pending.routes;
                this.pending = null;
                this.sendRoutes(routes);
            },

            clearPending: function () {
                this.pending = null;
            },

            previous: function () {
                var self = this, d = this.dest;
                if (!d || this.previousFor(d) === null) return;
                this.busy = true;
                post(window.VIDEOHUB_URLS.previous, { ip: this.ip, dest: d.index })
                    .then(function (snap) { self.apply(snap); })
                    .catch(function (e) { self.toast(e.message, 'error'); })
                    .finally(function () { self.busy = false; });
            },

            toggleLock: function () {
                var d = this.dest;
                if (!d) return;
                if (d.lock === 'L') {
                    if (!window.confirm('Force ' + d.label + ' unlocked? Another panel locked it.')) return;
                    this.sendLock(d, 'force');
                    return;
                }
                this.sendLock(d, d.lock === 'O' ? 'unlock' : 'lock');
            },

            sendRoutes: function (routes) {
                var self = this;
                this.busy = true;
                post(window.VIDEOHUB_URLS.route, { ip: this.ip, routes: routes })
                    .then(function (snap) { self.apply(snap); self.revealSource(); })
                    .catch(function (e) { self.toast(e.message, 'error'); })
                    .finally(function () { self.busy = false; });
            },

            sendLock: function (out, mode) {
                var self = this;
                this.busy = true;
                post(window.VIDEOHUB_URLS.lock, { ip: this.ip, dest: out.index, mode: mode })
                    .then(function (snap) { self.apply(snap); })
                    .catch(function (e) { self.toast(e.message, 'error'); })
                    .finally(function () { self.busy = false; });
            },

            onKey: function (e) {
                if (!this.ready || this.dialog) return;
                var tag = (e.target && e.target.tagName) || '';
                if (tag === 'INPUT' || tag === 'TEXTAREA') return;
                if (e.key === 'Enter' && this.pending) { e.preventDefault(); this.take(); return; }
                if (e.key === 'Escape') { this.pending = null; this.salvoMenu = this.fileMenu = false; return; }
                var n = this.outputs.length, m = this.inputs.length;
                if (!n || !m) return;
                if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                    e.preventDefault();
                    this.selected = (this.selected + (e.key === 'ArrowRight' ? 1 : n - 1)) % n;
                    this.pending = null;
                    this.revealSource();
                    return;
                }
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    var d = this.dest;
                    if (!d || d.lock === 'L') return;
                    var from = this.pending && !this.pending.name ? this.pending.routes[0][1]
                        : (d.source === null ? 0 : d.source);
                    var next = (from + (e.key === 'ArrowDown' ? 1 : m - 1)) % m;
                    this.pending = next === d.source ? null : { routes: [[d.index, next]] };
                }
            },

            revealSource: function () {
                var self = this;
                this.$nextTick(function () {
                    var d = self.dest;
                    if (!d || d.source === null) return;
                    var el = self.$root.querySelector('.vh-src[data-index="' + d.source + '"]');
                    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                });
            },

            // ---- labels -----------------------------------------------------
            rename: function (kind, item) {
                var self = this;
                this.openDialog({
                    title: 'Rename ' + kind + ' ' + (item.index + 1),
                    value: item.label,
                    note: 'Saved on the Videohub itself, up to 64 characters.',
                    ok: function (value) {
                        return post(window.VIDEOHUB_URLS.label, { ip: self.ip, kind: kind, index: item.index, label: value })
                            .then(function (snap) { self.apply(snap); });
                    }
                });
            },

            // ---- salvos -----------------------------------------------------
            loadSalvos: function () {
                var self = this;
                fetch(window.VIDEOHUB_URLS.salvos + '?ip=' + encodeURIComponent(this.ip), { cache: 'no-store' })
                    .then(function (r) { return r.json(); })
                    .then(function (body) { self.salvos = body.salvos || []; })
                    .catch(function () { /* menu shows what it had */ });
            },

            askSalvoName: function () {
                var self = this;
                this.openDialog({
                    title: 'Save current routing as a salvo',
                    value: '',
                    note: 'All ' + this.outputs.length + ' destinations, as they are routed now.',
                    ok: function (value) {
                        return post(window.VIDEOHUB_URLS.salvos, { ip: self.ip, name: value })
                            .then(function (body) {
                                self.salvos = body.salvos || [];
                                self.toast('Salvo ' + value + ' saved.', 'ok');
                            });
                    }
                });
            },

            fireSalvo: function (salvo) {
                this.salvoMenu = false;
                var self = this;
                var routes = salvo.routes.filter(function (r) {
                    var out = self.outputs[r[0]];
                    return out && out.lock !== 'L' && r[1] < self.inputs.length;
                });
                var skipped = salvo.routes.length - routes.length;
                if (skipped) this.toast(skipped + ' route(s) skipped: locked or outside this hub.', 'warn');
                if (!routes.length) return;
                var anyTake = this.useTake || routes.some(function (r) { return self.needsTake(r[0]); });
                if (anyTake) { this.pending = { routes: routes, name: salvo.name }; return; }
                this.sendRoutes(routes);
            },

            deleteSalvo: function (salvo) {
                var self = this;
                if (!window.confirm('Delete salvo ' + salvo.name + '?')) return;
                post(window.VIDEOHUB_URLS.salvos, { ip: this.ip, name: salvo.name }, 'DELETE')
                    .then(function (body) { self.salvos = body.salvos || []; })
                    .catch(function (e) { self.toast(e.message, 'error'); });
            },

            // ---- routes file ------------------------------------------------
            importRoutes: function (event) {
                var self = this, file = event.target.files && event.target.files[0];
                event.target.value = '';
                this.fileMenu = false;
                if (!file) return;
                file.text().then(function (text) {
                    if (!window.confirm('Load the routing in ' + file.name + ' onto ' +
                        (self.device.friendly_name || self.ip) + '? Every destination in the file is routed now.')) return;
                    self.busy = true;
                    return post(window.VIDEOHUB_URLS.routesFile, { ip: self.ip, text: text })
                        .then(function (snap) { self.apply(snap); self.toast('Routes loaded.', 'ok'); });
                }).catch(function (e) { self.toast(e.message, 'error'); })
                  .finally(function () { self.busy = false; });
            },

            // ---- dialog and toasts -----------------------------------------
            openDialog: function (spec) {
                var self = this;
                this.dialog = spec;
                this.dialogValue = spec.value || '';
                this.$nextTick(function () {
                    var input = self.$refs.dialogInput;
                    if (input) { input.focus(); input.select(); }
                });
            },

            dialogOk: function () {
                var self = this, spec = this.dialog, value = this.dialogValue.trim();
                if (!spec) return;
                if (!value && spec.title.indexOf('salvo') !== -1) return;
                spec.ok(value).then(function () { self.dialog = null; })
                    .catch(function (e) { self.toast(e.message, 'error'); });
            },

            toast: function (text, kind) {
                var self = this, id = ++this._toastId;
                this.toasts.push({ id: id, text: text, kind: kind || 'info' });
                setTimeout(function () {
                    self.toasts = self.toasts.filter(function (t) { return t.id !== id; });
                }, kind === 'error' ? 6000 : 3500);
            },

            // ---- fill the window --------------------------------------------
            // One size for every button (and every matrix cell): the largest at
            // which the page fits the window, as the control page's fit does.
            queueFit: function () {
                var self = this;
                if (this._fitQueued) return;
                this._fitQueued = true;
                requestAnimationFrame(function () { self._fitQueued = false; self.fit(); });
            },

            fit: function () {
                var main = document.querySelector('main') || document.body;
                var root = this.$root;
                var view = this.view === 'buttons' ? this.$refs.buttonsView : this.$refs.matrixView;
                // Fits when the view's last edge is inside the window (the
                // scroll height of <main> does not see this page's overflow).
                var fits = function () {
                    return !view || view.getBoundingClientRect().bottom <= main.getBoundingClientRect().bottom - 6;
                };
                if (!view || !view.getBoundingClientRect().height) {
                    var self = this;
                    setTimeout(function () { self.queueFit(); }, 100);   // not shown yet
                    return;
                }
                main.scrollTop = 0;
                var size;
                if (this.view === 'buttons') {
                    root.style.removeProperty('--vh-btn-h');
                    for (size = 120; size > 40; size -= 4) {
                        root.style.setProperty('--vh-btn', size + 'px');
                        if (fits()) break;
                    }
                    root.style.setProperty('--vh-btn', size + 'px');
                    // The next size up adds a row, so some height is left: the
                    // buttons take it, keeping their width.
                    var spare = main.getBoundingClientRect().bottom - 6 - view.getBoundingClientRect().bottom;
                    var rows = 0;
                    view.querySelectorAll('.vh-grid').forEach(function (grid) {
                        var cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length || 1;
                        rows += Math.ceil(grid.children.length / cols);
                    });
                    if (spare > 0 && rows) {
                        var h = Math.min(size * 1.6, size + Math.floor(spare / rows));
                        root.style.setProperty('--vh-btn-h', h + 'px');
                    }
                } else {
                    // Cells take the card's width and height between them,
                    // each axis on its own (40 sources across rarely need the
                    // height 40 destinations do); below the minimum it scrolls.
                    var table = view.querySelector('table');
                    var head = table && table.tHead;
                    var rowhead = table && table.querySelector('.vh-rowhead');
                    var cols = Math.max(1, this.inputs.length), rowsN = Math.max(1, this.outputs.length);
                    var w = view.clientWidth - (rowhead ? rowhead.offsetWidth : 176) - 2;
                    var h = view.clientHeight - (head ? head.offsetHeight : 104) - 2;
                    var cw = Math.max(16, Math.min(64, Math.floor(w / cols)));
                    var ch = Math.max(16, Math.min(44, Math.floor(h / rowsN)));
                    root.style.setProperty('--vh-cw', cw + 'px');
                    root.style.setProperty('--vh-ch', ch + 'px');
                }
            }
        };
    };
})();
