/* Connect page (local addition): Recent switchers shown by bare IP get
 * their name as soon as the server has read it (atem_control/localhooks.py
 * reads an unnamed Recent switcher once, in the background). Asks the
 * upstream lookup for each nameless row for a little while, then stops. */
(function () {
    'use strict';
    var TRIES = 12, EVERY_MS = 2000;

    function nameless() {
        var rows = [];
        document.querySelectorAll('button[onclick^="setIP("]').forEach(function (btn) {
            if (btn.querySelector('.recent-by-name')) return;
            var m = /setIP\('([^']+)'\)/.exec(btn.getAttribute('onclick') || '');
            if (m) rows.push({ btn: btn, ip: m[1] });
        });
        return rows;
    }

    function label(btn, name, ip) {
        var n = document.createElement('span');
        n.className = 'recent-by-name';
        n.textContent = name;
        var i = document.createElement('span');
        i.className = 'recent-by-ip';
        i.textContent = ip;
        btn.replaceChildren(n, i);
        btn.title = name + ' - ' + ip;
    }

    var rows = nameless(), tries = 0;
    if (!rows.length) return;

    function ask() {
        tries += 1;
        rows = rows.filter(function (row) { return !row.btn.querySelector('.recent-by-name'); });
        if (!rows.length || tries > TRIES) return;
        rows.forEach(function (row) {
            fetch('/atem/api/lookup-name/?ip=' + encodeURIComponent(row.ip), { cache: 'no-store' })
                .then(function (r) { return r.json(); })
                .then(function (d) { if (d.found && d.name) label(row.btn, d.name, row.ip); })
                .catch(function () { /* next try */ });
        });
        setTimeout(ask, EVERY_MS);
    }

    ask();
})();
