/* Connect page, streaming-encoder section (local addition): Bonjour-found and
 * recent Web Presenters / Streaming Encoders, plus an address field; each
 * opens /atem/streamer/?ip=. */
(function () {
    'use strict';
    var form = document.getElementById('seConnectForm');
    if (!form) return;
    var pageUrl = form.dataset.pageUrl;
    var input = document.getElementById('seIp');
    var error = document.getElementById('seIpError');
    var found = document.getElementById('seFound');
    var foundEmpty = document.getElementById('seFoundEmpty');
    var recent = document.getElementById('seRecent');
    var recentWrap = document.getElementById('seRecentWrap');
    var IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

    function open(ip) {
        window.location.href = pageUrl + '?ip=' + encodeURIComponent(ip);
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var ip = input.value.trim();
        if (!IPV4.test(ip)) { error.classList.remove('hidden'); input.focus(); return; }
        error.classList.add('hidden');
        open(ip);
    });

    function hubButton(hub, outline) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm ' + (outline ? 'btn-outline btn-primary' : 'bg-base-300 border-0') + ' gap-2';
        btn.title = (hub.model ? hub.model + ' · ' : '') + hub.ip;
        var name = document.createElement('span');
        name.textContent = hub.name || hub.ip;
        var ip = document.createElement('span');
        ip.className = 'brand-data opacity-60 text-xs';
        ip.textContent = hub.ip;
        btn.appendChild(name);
        if (hub.name && hub.name !== hub.ip) btn.appendChild(ip);
        btn.addEventListener('click', function () { open(hub.ip); });
        return btn;
    }

    function render(data) {
        var hubs = data.devices || [], recents = data.recent || [];
        found.replaceChildren.apply(found, hubs.map(function (h) { return hubButton(h, false); }));
        foundEmpty.classList.toggle('hidden', hubs.length > 0);
        recent.replaceChildren.apply(recent, recents.map(function (h) { return hubButton(h, true); }));
        recentWrap.classList.toggle('hidden', recents.length === 0);
    }

    function poll() {
        fetch(pageUrl + 'api/discovered/', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(render)
            .catch(function () { /* next poll retries */ });
    }

    poll();
    setInterval(poll, 3000);
    window.seConnectRefresh = poll;   // the page's Scan network refreshes this card
})();
