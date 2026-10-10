// Fill-the-window layout (local change), loaded by base.html with
// fit-window.css.
//
// Every square control (Program/Preview, USK, DSK) is one size, --atem-btn.
// Upstream fixes it per breakpoint, so a narrow card can be smaller than
// its row of buttons, and a big window leaves space unused. This picks the
// largest size, between MIN_BTN and MAX_BTN, at which no card's content
// overflows sideways and the page fits the window's height (see fit()).
// When the page cannot fit the height at any size, it scrolls: as little as
// possible in a landscape window, and with the biggest buttons the width
// allows in a stacked (portrait or phone) layout.
//
// Off for this browser: open the page with ?fit=0 (?fit=1 turns it back on,
// ?fit=debug shows what it picked).
(function () {
  var MIN_BTN = 36;    // px
  var MAX_BTN = 96;    // px
  var STEP = 2;        // px

  var param = new URLSearchParams(location.search).get('fit');
  try {
    if (param === '0') localStorage.setItem('webatem-fit', 'off');
    if (param === '1') localStorage.removeItem('webatem-fit');
    if (localStorage.getItem('webatem-fit') === 'off') return;
  } catch (e) { /* storage blocked: fit stays on */ }

  document.documentElement.classList.add('wa-fit');

  var queued = false;
  var debug = null;
  if (param === 'debug') {
    debug = document.createElement('div');
    debug.style.cssText = 'position:fixed;left:4px;bottom:4px;z-index:99999;' +
      'font:12px monospace;background:#000;color:#0f0;padding:2px 4px';
    document.body.appendChild(debug);
  }

  function scroller() {
    return document.querySelector('main') || document.body;
  }

  // The grid that carries --atem-btn on the control page; none elsewhere.
  function surface() {
    var grid = document.querySelector('.controls-transition > .grid');
    return grid && grid.offsetParent ? grid : null;
  }

  var BOXES = '.card-body, .card-body > .grid > div, .atem-bus';

  // How far, in px, the cards' contents stick out sideways in total, and
  // the box that sticks out most (for ?fit=debug).
  function sideways(grid) {
    var boxes = grid.querySelectorAll(BOXES);
    var total = 0, worst = null, worstBy = 0;
    for (var i = 0; i < boxes.length; i++) {
      var by = boxes[i].scrollWidth - boxes[i].clientWidth - 1;
      if (by > 0) {
        total += by;
        if (by > worstBy) { worstBy = by; worst = boxes[i]; }
      }
    }
    return { total: total, worst: worst };
  }

  function describe(el) {
    if (!el) return '-';
    var card = el.closest('.card');
    var title = card && card.querySelector('.card-title, h2');
    return (title ? title.textContent.trim().split(/\s+/)[0] : '?') + ' ' +
      el.scrollWidth + '>' + el.clientWidth;
  }

  function setSize(grid, px) {
    grid.style.setProperty('--atem-btn', px + 'px');
  }

  // Every size from MAX_BTN down is tried, because overflow is not
  // monotonic: rows of buttons stick out when they are big, and some
  // labels (DSK 1, the rate rows) when they are small. The pick is the
  // largest size with the least sideways overflow that also fits the
  // window's height; failing that, the largest with the least overflow,
  // and the page scrolls. Overflow that no size removes (a rate row in a
  // card too narrow for it) counts against every size alike.
  function fit() {
    queued = false;
    var grid = surface();
    if (!grid) return;
    var el = scroller();
    var tried = [];
    var least = Infinity;
    for (var px = MAX_BTN; px >= MIN_BTN; px -= STEP) {
      setSize(grid, px);
      var side = sideways(grid);
      var down = el.scrollHeight > el.clientHeight + 2;
      tried.push({ px: px, side: side, down: down, height: el.scrollHeight });
      if (side.total < least) least = side.total;
    }
    var pick = null, scrolls = false;
    for (var i = 0; i < tried.length && !pick; i++) {
      if (tried[i].side.total === least && !tried[i].down) pick = tried[i];
    }
    if (!pick) {
      // Too short a window for any size. In the landscape rows, scroll as
      // little as possible; in portrait or on a phone, where the page
      // scrolls anyway, keep the buttons as big as the width allows.
      scrolls = true;
      // Landscape rows put Keys beside Program; the portrait and stacked
      // layouts put it below the buses.
      var areas = getComputedStyle(grid).gridTemplateAreas;
      var stacked = areas === 'none' || areas.indexOf('keys') > areas.indexOf('pvw');
      for (var j = 0; j < tried.length; j++) {
        var t = tried[j];
        if (t.side.total !== least) continue;
        if (!pick || (!stacked && t.height < pick.height)) pick = t;
      }
    }
    setSize(grid, pick.px);
    if (debug) {
      var above = tried[tried.indexOf(pick) - 1];
      debug.textContent = 'fit btn=' + pick.px + 'px' + (scrolls ? ' (scrolls)' : '') +
        ' main=' + el.clientHeight + '/' + el.scrollHeight +
        ' win=' + innerWidth + 'x' + innerHeight +
        ' stuck=' + least + 'px ' + describe(pick.side.worst) +
        (above ? ' next:' + (above.down ? 'height ' : '') + describe(above.side.worst) : '');
    }
  }

  function queue() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(fit);
  }

  window.addEventListener('resize', queue);
  if (window.ResizeObserver) {
    // Content changes (the switcher connecting, an M/E added) resize
    // <main>'s children. The fit always searches from scratch, so its own
    // result settles on the same sizes and does not fire it again.
    var observer = new ResizeObserver(queue);
    var watch = function () {
      var el = scroller();
      for (var i = 0; i < el.children.length; i++) observer.observe(el.children[i]);
    };
    watch();
    new MutationObserver(function () { watch(); queue(); })
      .observe(scroller(), { childList: true });
  }
  queue();
})();
