/* Connect page, one scan for every card (local addition). "Scan network"
 * runs the ATEM card's sweep through its own (hidden) Rescan button, so the
 * ATEM list fills exactly as upstream fills it, and the Videohub and
 * encoder sweeps alongside; the cards then refresh their lists. */
(function () {
    'use strict';
    var btn = document.getElementById('netScanBtn');
    var input = document.getElementById('netScanSubnet');
    var note = document.getElementById('netScanNote');
    if (!btn || !input) return;

    // Prefill with the host's own subnet, as the ATEM card does.
    fetch('/atem/videohub/api/discovered/', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d.subnet && !input.value) input.value = d.subnet; })
        .catch(function () { /* the field stays empty: the server uses its own network */ });

    function sweep(url, subnet) {
        return fetch(url + (subnet ? '?subnet=' + encodeURIComponent(subnet) : ''), { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) { return (d.found || d.atems || []).length; })
            .catch(function () { return 0; });
    }

    function scan() {
        var subnet = input.value.trim();
        var original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span> Scanning…';
        note.textContent = '';
        // ATEMs: the upstream card's own sweep and rendering.
        var atemSubnet = document.getElementById('scanSubnet');
        var atemBtn = document.getElementById('scanBtn');
        if (atemSubnet && atemBtn) {
            atemSubnet.value = subnet;
            atemBtn.click();
        }
        Promise.all([sweep('/atem/videohub/api/scan/', subnet), sweep('/atem/streamer/api/scan/', subnet)])
            .then(function (counts) {
                if (window.vhConnectRefresh) window.vhConnectRefresh();
                if (window.seConnectRefresh) window.seConnectRefresh();
                note.textContent = 'Scanned ' + (subnet || 'this network') + ': ' +
                    counts[0] + ' Videohub' + (counts[0] === 1 ? '' : 's') + ', ' +
                    counts[1] + ' streaming encoder' + (counts[1] === 1 ? '' : 's') +
                    '. ATEMs appear in their card.';
            })
            .finally(function () { btn.disabled = false; btn.innerHTML = original; });
    }

    btn.addEventListener('click', scan);

    // The ATEM card says what the device cards say when it has found nothing
    // (its own hint names the Rescan button this page hides).
    var atemList = document.getElementById('discoveryList');
    var atemEmpty = document.getElementById('discoveryEmpty');
    if (atemList && atemEmpty) {
        atemEmpty.textContent = 'Nothing found yet. Press Scan network, or enter an address.';
        var sync = function () { atemEmpty.classList.toggle('hidden', atemList.children.length > 0); };
        sync();
        new MutationObserver(sync).observe(atemList, { childList: true });
    }
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); scan(); }
    });
})();
