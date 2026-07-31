/* ===== Desktop behaviours: zoom, find, navigation, help =====
   These are implemented in the page rather than in native menus so they
   behave identically in the macOS WKWebView, the Windows WebView2 shell,
   and a plain browser tab. */
'use strict';

(function () {
  // navigator.platform is deprecated, so prefer userAgentData and keep the
  // old properties only as fallbacks. Anything that is not macOS (Windows
  // WebView2, Linux, a plain browser) gets Ctrl.
  const platform = (
    navigator.userAgentData?.platform ||
    navigator.platform ||
    navigator.userAgent ||
    ''
  ).toUpperCase();
  const isMac = platform.includes('MAC');
  const accel = (e) => (isMac ? e.metaKey : e.ctrlKey);
  const LS_ZOOM = 'ai-screening.zoom';

  /* ---------------- zoom ---------------- */
  const STEPS = [0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.4, 1.6, 1.8, 2];
  let zoom = parseFloat(localStorage.getItem(LS_ZOOM) || '1');
  if (!STEPS.includes(zoom)) zoom = 1;

  function applyZoom(z, announce = true) {
    zoom = Math.min(STEPS[STEPS.length - 1], Math.max(STEPS[0], z));
    // The stylesheet is px-based, so scaling the root font size would do
    // nothing. `zoom` reflows properly (unlike transform: scale) and is
    // supported by both WKWebView and WebView2.
    document.documentElement.style.zoom = zoom === 1 ? '' : String(zoom);
    // Full-height rules divide by this, otherwise zooming out shrinks the
    // sidebar and page shell and leaves dead space at the bottom.
    document.documentElement.style.setProperty('--zoom', String(zoom));
    localStorage.setItem(LS_ZOOM, String(zoom));
    if (announce) flash(Math.round(zoom * 100) + '%');
  }
  const stepZoom = (dir) => {
    const i = STEPS.indexOf(zoom);
    const next = STEPS[Math.min(STEPS.length - 1, Math.max(0, (i < 0 ? 3 : i) + dir))];
    applyZoom(next);
  };
  applyZoom(zoom, false);

  let flashTimer;
  function flash(text) {
    let el = document.getElementById('zoom-flash');
    if (!el) {
      el = document.createElement('div');
      el.id = 'zoom-flash';
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.add('on');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => el.classList.remove('on'), 900);
  }

  /* ---------------- find ---------------- */
  let findOpen = false, matches = [], activeMatch = -1, lastQuery = '';

  function findBar() {
    let bar = document.getElementById('find-bar');
    if (bar) return bar;
    bar = document.createElement('div');
    bar.id = 'find-bar';
    bar.innerHTML = `
      <input type="text" id="find-input" placeholder="Find in page" autocomplete="off" spellcheck="false">
      <span id="find-count">0/0</span>
      <button class="find-btn" id="find-prev" title="Previous (Shift+Enter)">&#8593;</button>
      <button class="find-btn" id="find-next" title="Next (Enter)">&#8595;</button>
      <button class="find-btn" id="find-close" title="Close (Esc)">&#10005;</button>`;
    document.body.appendChild(bar);
    bar.querySelector('#find-next').addEventListener('click', () => cycle(1));
    bar.querySelector('#find-prev').addEventListener('click', () => cycle(-1));
    bar.querySelector('#find-close').addEventListener('click', closeFind);
    const input = bar.querySelector('#find-input');
    input.addEventListener('input', () => runFind(input.value));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); cycle(e.shiftKey ? -1 : 1); }
      else if (e.key === 'Escape') { e.preventDefault(); closeFind(); }
    });
    return bar;
  }

  // Search area excludes the sidebar so hits land on content, not chrome.
  const scope = () => document.querySelector('.main') || document.body;

  function clearMarks() {
    const root = scope();
    root.querySelectorAll('mark.find-hit').forEach(m => {
      const parent = m.parentNode;
      parent.replaceChild(document.createTextNode(m.textContent), m);
      parent.normalize();
    });
    matches = []; activeMatch = -1;
  }

  function runFind(q) {
    clearMarks();
    lastQuery = q;
    const count = document.getElementById('find-count');
    if (!q || q.length < 2) { if (count) count.textContent = '0/0'; return; }

    const needle = q.toLowerCase();
    const walker = document.createTreeWalker(scope(), NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const p = node.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        // never rewrite inside form controls, scripts, or the find bar itself
        if (p.closest('#find-bar, script, style, textarea, input, select')) return NodeFilter.FILTER_REJECT;
        return node.nodeValue.toLowerCase().includes(needle)
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    const targets = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) targets.push(n);

    targets.forEach(node => {
      const text = node.nodeValue;
      const frag = document.createDocumentFragment();
      let i = 0, at;
      while ((at = text.toLowerCase().indexOf(needle, i)) !== -1) {
        if (at > i) frag.appendChild(document.createTextNode(text.slice(i, at)));
        const mark = document.createElement('mark');
        mark.className = 'find-hit';
        mark.textContent = text.substr(at, q.length);
        frag.appendChild(mark);
        matches.push(mark);
        i = at + q.length;
      }
      if (i < text.length) frag.appendChild(document.createTextNode(text.slice(i)));
      node.parentNode.replaceChild(frag, node);
    });

    if (matches.length) cycle(1); else if (count) count.textContent = '0/0';
  }

  function cycle(dir) {
    if (!matches.length) return;
    if (activeMatch >= 0 && matches[activeMatch]) matches[activeMatch].classList.remove('current');
    activeMatch = (activeMatch + dir + matches.length) % matches.length;
    const m = matches[activeMatch];
    m.classList.add('current');
    m.scrollIntoView({ block: 'center', behavior: 'auto' });
    const count = document.getElementById('find-count');
    if (count) count.textContent = `${activeMatch + 1}/${matches.length}`;
  }

  function openFind() {
    findBar().classList.add('on');
    findOpen = true;
    const input = document.getElementById('find-input');
    input.value = lastQuery;
    input.focus();
    input.select();
    if (lastQuery) runFind(lastQuery);
  }
  function closeFind() {
    const bar = document.getElementById('find-bar');
    if (bar) bar.classList.remove('on');
    findOpen = false;
    clearMarks();
  }

  /* ---------------- help overlay ---------------- */
  const SHORTCUTS = [
    ['Zoom in', 'Plus'], ['Zoom out', 'Minus'], ['Reset zoom', '0'],
    ['Find in page', 'F'], ['Next / previous match', 'Enter / Shift+Enter'],
    ['Go to section', '1 to 6'], ['Reload', 'R'],
    ['Close find or dialog', 'Esc'], ['This list', '/'],
  ];
  function toggleHelp() {
    let el = document.getElementById('help-overlay');
    if (el) { el.remove(); return; }
    const key = isMac ? '⌘' : 'Ctrl';
    el = document.createElement('div');
    el.id = 'help-overlay';
    el.innerHTML = `<div class="help-panel">
      <h2>Keyboard shortcuts</h2>
      <dl>${SHORTCUTS.map(([label, k]) =>
        `<dt>${label}</dt><dd><kbd>${k === 'Enter / Shift+Enter' ? k : key + ' ' + k}</kbd></dd>`).join('')}</dl>
      <button class="btn sm" id="help-close">Close</button>
    </div>`;
    document.body.appendChild(el);
    el.addEventListener('click', (e) => { if (e.target === el) el.remove(); });
    el.querySelector('#help-close').addEventListener('click', () => el.remove());
  }

  /* ---------------- key handling ---------------- */
  document.addEventListener('keydown', (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')
      && document.activeElement.id !== 'find-input';

    if (accel(e)) {
      switch (e.key) {
        case '=': case '+': e.preventDefault(); stepZoom(1); return;
        case '-': case '_': e.preventDefault(); stepZoom(-1); return;
        case '0': e.preventDefault(); applyZoom(1); return;
        case 'f': case 'F': e.preventDefault(); openFind(); return;
        case 'r': case 'R': e.preventDefault(); location.reload(); return;
        case '/': e.preventDefault(); toggleHelp(); return;
      }
      if (!typing && e.key >= '1' && e.key <= '6') {
        e.preventDefault();
        const views = ['projects', 'criteria', 'import', 'screen', 'results', 'settings'];
        if (window.go) window.go(views[Number(e.key) - 1]);
        return;
      }
    }
    if (e.key === 'Escape') {
      const help = document.getElementById('help-overlay');
      if (help) { help.remove(); return; }
      if (findOpen) closeFind();
    }
    if (e.key === '?' && !typing && !findOpen) { e.preventDefault(); toggleHelp(); }
  });

  // Wheel zoom takes ctrlKey on every platform, not just the accel key:
  // a trackpad pinch is delivered as ctrl+wheel on macOS too, so keying this
  // off metaKey alone would break pinch-to-zoom there.
  window.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !accel(e)) return;
    e.preventDefault();
    stepZoom(e.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  // Expose for the native menu bar to call into.
  window.appShortcuts = {
    zoomIn: () => stepZoom(1),
    zoomOut: () => stepZoom(-1),
    zoomReset: () => applyZoom(1),
    find: openFind,
    help: toggleHelp,
  };
})();
