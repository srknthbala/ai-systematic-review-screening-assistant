/* ===== AI Screening: single-page app ===== */
'use strict';

// ---------- tiny helpers ----------
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const pct = (x) => (x == null ? 'n/a' : Math.round(x * 100) + '%');

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const ct = res.headers.get('content-type') || '';
  let data = ct.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = (data && data.detail) || res.statusText || 'Request failed';
    if (Array.isArray(msg)) msg = msg.map(m => m.msg || JSON.stringify(m)).join('; ');
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}
function toast(msg, kind = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  $('#toast-wrap').appendChild(t);
  setTimeout(() => t.classList.add('out'), 3200);
  setTimeout(() => t.remove(), 3600);
}

// ---------- state ----------
const S = {
  view: 'projects',
  projects: [],
  currentId: null,
  options: { review_types: [], question_types: [], areas_of_research: [] },
  pollers: [],
  // Which workflow steps are complete. Drives the ticks in the sidebar.
  flags: { criteria: false, apiKey: false },
};
function addPoller(id) { S.pollers.push(id); }
function clearPollers() { S.pollers.forEach(clearInterval); S.pollers = []; }
const currentProject = () => S.projects.find(p => p.id === S.currentId);

// ---------- boot ----------
async function boot() {
  try {
    S.options = await api('/api/options');
    await loadProjects();
  } catch (e) { toast(e.message, 'err'); }

  $$('.nav-item').forEach(b => b.addEventListener('click', () => { go(b.dataset.view); closeDrawer(); }));
  $('#project-select').addEventListener('change', async (e) => {
    const id = Number(e.target.value);
    if (!id) return;
    await api('/api/projects/current', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: id }) });
    S.currentId = id;
    await refreshFlags();
    render();
  });

  // mobile drawer
  $('#sidebar-toggle').addEventListener('click', () => {
    $('#sidebar').classList.contains('open') ? closeDrawer() : openDrawer();
  });
  $('#scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
  window.addEventListener('resize', debounce(positionRail, 80));
  // A file dropped outside the dropzone would otherwise navigate the page away.
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => e.preventDefault());

  await refreshFlags();
  go('projects');
}

function openDrawer() {
  $('#sidebar').classList.add('open');
  $('#scrim').hidden = false;
  $('#sidebar-toggle').setAttribute('aria-expanded', 'true');
}
function closeDrawer() {
  $('#sidebar').classList.remove('open');
  $('#scrim').hidden = true;
  $('#sidebar-toggle').setAttribute('aria-expanded', 'false');
}

// Criteria / API-key completeness isn't in the project payload, so pull it
// from the screen-status endpoint (cheap, local) when a project is active.
async function refreshFlags() {
  if (!S.currentId) { S.flags = { criteria: false, apiKey: false }; return; }
  try {
    const st = await api('/api/screen/status?project_id=' + S.currentId);
    S.flags = { criteria: !!st.has_criteria, apiKey: !!st.api_key_set };
  } catch { /* leave flags as-is */ }
}

async function loadProjects() {
  const d = await api('/api/projects');
  S.projects = d.projects;
  S.currentId = d.current_project_id;
  renderProjectSelect();
}
function renderProjectSelect() {
  const sel = $('#project-select');
  if (!S.projects.length) { sel.innerHTML = '<option value="">No projects yet</option>'; return; }
  sel.innerHTML = S.projects.map(p =>
    `<option value="${p.id}" ${p.id === S.currentId ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
}

function go(view) { S.view = view; render(); }
function setTopRight(html) { $('#topbar-right').innerHTML = html || ''; }

const VIEW_META = {
  projects: ['Projects', 'Create a review and pick which one you are working on.'],
  criteria: ['Criteria', 'Define PICOS include / exclude rules for the active project.'],
  import: ['Import', 'Load RIS or MEDLINE exports and deduplicate across databases.'],
  screen: ['Screen', 'Run a sample test, then screen the full set via the Batches API.'],
  results: ['Results', 'Filter decisions and export them for your PRISMA flow.'],
  settings: ['Settings', 'API key, model, and connection check.'],
};

// Steps a user has finished, so the sidebar can show progress at a glance.
function doneSteps() {
  const p = currentProject();
  const recs = p ? (p.unique_records || 0) : 0;
  const screened = p ? (p.screened || 0) : 0;
  return {
    projects: S.projects.length > 0,
    criteria: S.flags.criteria,
    import: recs > 0,
    screen: screened > 0,
    results: screened > 0,
    settings: S.flags.apiKey,
  };
}

function positionRail() {
  const rail = $('#nav-rail');
  const active = $('.nav-item.active');
  if (!rail || !active) { if (rail) rail.classList.remove('on'); return; }
  rail.style.setProperty('--rail-y', active.offsetTop + 'px');
  rail.style.height = active.offsetHeight + 'px';
  rail.classList.add('on');
}

function render() {
  clearPollers();
  const done = doneSteps();
  $$('.nav-item').forEach(b => {
    b.classList.toggle('active', b.dataset.view === S.view);
    b.classList.toggle('done', !!done[b.dataset.view]);
  });
  positionRail();
  const [title, sub] = VIEW_META[S.view];
  $('#section-title').textContent = title;
  $('#section-sub').textContent = sub;
  setTopRight('');
  renderProjectSelect();
  ({ projects: viewProjects, criteria: viewCriteria, import: viewImport, screen: viewScreen, results: viewResults, settings: viewSettings }[S.view])();
}

function needProject(host) {
  if (S.currentId) return false;
  host.innerHTML = emptyState('No active project', 'Create or select a project first. All criteria, imports, and results are scoped to a project.',
    '<button class="btn primary" onclick="go(\'projects\')">Go to Projects</button>');
  return true;
}
const ICON_EMPTY = '<svg viewBox="0 0 24 24"><path d="M3 5h18l-7 8.5V21l-4 -2v-5.5L3 5Z"/></svg>';
function emptyState(title, body, action = '') {
  return `<div class="card"><div class="empty"><div class="ico">${ICON_EMPTY}</div><h3>${esc(title)}</h3><p class="muted">${esc(body)}</p>${action}</div></div>`;
}
window.go = go;

/* ============================================================= 1. PROJECTS */
function viewProjects() {
  const host = $('#view');
  const opt = (arr, v) => arr.map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('');
  host.innerHTML = `
    <div class="card">
      <p class="card-title">New project</p>
      <p class="card-sub">Mirrors Covidence review settings. The new project becomes active automatically.</p>
      <div class="grid-2">
        <label class="field"><span>Review name</span><input id="np-name" type="text" placeholder="e.g. NMES &amp; muscle morphology after stroke"></label>
        <label class="field"><span>Review type</span><select id="np-rt"><option value="">(none)</option>${opt(S.options.review_types)}</select></label>
        <label class="field"><span>Question type</span><select id="np-qt"><option value="">(none)</option>${opt(S.options.question_types)}</select></label>
        <label class="field"><span>Area of research</span><select id="np-ar"><option value="">(none)</option>${opt(S.options.areas_of_research)}</select></label>
      </div>
      <label class="field"><span>Notes</span><textarea id="np-notes" rows="2" placeholder="Free-text notes"></textarea></label>
      <button class="btn primary" id="np-create">Create project</button>
    </div>
    <h2 class="section" style="margin-top:26px">Your projects</h2>
    <div id="proj-list"></div>`;

  $('#np-create').addEventListener('click', async () => {
    const name = $('#np-name').value.trim();
    if (!name) { toast('Enter a review name', 'err'); return; }
    try {
      await api('/api/projects', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, review_type: $('#np-rt').value, question_type: $('#np-qt').value, area_of_research: $('#np-ar').value, notes: $('#np-notes').value })
      });
      await loadProjects();
      toast('Project created', 'ok');
      viewProjects();
    } catch (e) { toast(e.message, 'err'); }
  });
  renderProjectList();
}

function renderProjectList() {
  const host = $('#proj-list');
  if (!S.projects.length) { host.innerHTML = emptyState('No projects yet', 'Create your first project above to begin.'); return; }
  host.innerHTML = `<div class="proj-grid">` + S.projects.map(p => {
    const meta = [p.review_type, p.question_type, p.area_of_research].filter(Boolean)
      .map(m => `<span class="badge neutral">${esc(m)}</span>`).join('');
    return `<div class="card proj-card ${p.id === S.currentId ? 'selected' : ''}" data-id="${p.id}">
      <div class="spread"><h3>${esc(p.name)}</h3>${p.id === S.currentId ? '<span class="badge accent">Active</span>' : ''}</div>
      <div class="proj-meta">${meta || '<span class="hint">No type set</span>'}</div>
      ${p.notes ? `<p class="hint" style="margin:0 0 4px">${esc(p.notes)}</p>` : ''}
      <div class="proj-stats"><span><b>${p.unique_records ?? 0}</b> unique records</span><span><b>${p.screened ?? 0}</b> screened</span></div>
      <div class="row" style="margin-top:14px">
        <button class="btn sm" data-act="select">${p.id === S.currentId ? 'Selected' : 'Select'}</button>
        <button class="btn sm" data-act="edit">Edit</button>
        <button class="btn sm danger" data-act="delete">Delete</button>
      </div>
    </div>`;
  }).join('') + `</div>`;

  $$('.proj-card', host).forEach(card => {
    const id = Number(card.dataset.id);
    card.querySelector('[data-act=select]').addEventListener('click', async (e) => {
      e.stopPropagation();
      await api('/api/projects/current', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: id }) });
      S.currentId = id; renderProjectList(); renderProjectSelect();
      toast('Project selected', 'ok');
    });
    card.querySelector('[data-act=edit]').addEventListener('click', (e) => { e.stopPropagation(); editProject(id); });
    card.querySelector('[data-act=delete]').addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('Delete this project and all its records, criteria, and results? This cannot be undone.')) return;
      await api('/api/projects/' + id, { method: 'DELETE' });
      await loadProjects(); toast('Project deleted', 'ok'); viewProjects();
    });
  });
}

function editProject(id) {
  const p = S.projects.find(x => x.id === id);
  const opt = (arr, v) => arr.map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('');
  const host = $('#view');
  host.innerHTML = `<div class="card" style="max-width:640px">
    <p class="card-title">Edit project</p>
    <div class="grid-2">
      <label class="field"><span>Review name</span><input id="ep-name" type="text" value="${esc(p.name)}"></label>
      <label class="field"><span>Review type</span><select id="ep-rt"><option value="">(none)</option>${opt(S.options.review_types, p.review_type)}</select></label>
      <label class="field"><span>Question type</span><select id="ep-qt"><option value="">(none)</option>${opt(S.options.question_types, p.question_type)}</select></label>
      <label class="field"><span>Area of research</span><select id="ep-ar"><option value="">(none)</option>${opt(S.options.areas_of_research, p.area_of_research)}</select></label>
    </div>
    <label class="field"><span>Notes</span><textarea id="ep-notes" rows="3">${esc(p.notes)}</textarea></label>
    <div class="row"><button class="btn primary" id="ep-save">Save changes</button><button class="btn ghost" id="ep-cancel">Cancel</button></div>
  </div>`;
  $('#ep-cancel').addEventListener('click', viewProjects);
  $('#ep-save').addEventListener('click', async () => {
    await api('/api/projects/' + id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: $('#ep-name').value, review_type: $('#ep-rt').value, question_type: $('#ep-qt').value, area_of_research: $('#ep-ar').value, notes: $('#ep-notes').value })
    });
    await loadProjects(); toast('Saved', 'ok'); viewProjects();
  });
}

/* ============================================================= 2. CRITERIA */
const PICOS = [
  { k: 'pop', n: 'P', t: 'Population' },
  { k: 'int', n: 'I', t: 'Intervention / Exposure' },
  { k: 'comp', n: 'C', t: 'Comparator / Context' },
  { k: 'out', n: 'O', t: 'Outcome' },
  { k: 'study', n: 'S', t: 'Study Characteristics' },
  { k: 'other', n: '+', t: 'Other' },
];

async function viewCriteria() {
  const host = $('#view');
  if (needProject(host)) return;
  setTopRight('<span class="save-state" id="crit-save"></span>');
  let c;
  try { c = (await api('/api/criteria?project_id=' + S.currentId)).criteria; }
  catch (e) { host.innerHTML = emptyState('Could not load criteria', e.message); return; }

  const box = (cat, kind) => {
    const field = `${cat.k}_${kind === 'inc' ? 'include' : 'exclude'}`;
    const label = kind === 'inc' ? 'Include' : 'Exclude';
    return `<div class="cbox ${kind}">
      <div class="cbox-label"><span class="dot"></span>${label}</div>
      <textarea data-field="${field}" placeholder="${label} criteria for ${esc(cat.t)}…">${esc(c[field])}</textarea>
    </div>`;
  };
  host.innerHTML = `
    <div class="card">
      <p class="card-title">PICOS criteria</p>
      <p class="card-sub">Six categories, paired include / exclude. Changes auto-save to the active project.</p>
      ${PICOS.map(cat => `<div class="criteria-cat">
        <div class="cat-head"><span class="num">${cat.n}</span><h3>${esc(cat.t)}</h3></div>
        <div class="cbox-pair">${box(cat, 'inc')}${box(cat, 'exc')}</div>
      </div>`).join('')}
    </div>
    <div class="card">
      <p class="card-title">Full-text exclusion reasons <span class="badge neutral">optional</span></p>
      <p class="card-sub">If non-empty, every EXCLUDE/MAYBE is tagged with the single best-fit reason from this list. If empty, the model writes a free-text reason instead.</p>
      <div class="row" style="margin-bottom:12px">
        <input id="reason-input" type="text" placeholder="e.g. Wrong population" style="max-width:320px">
        <button class="btn" id="reason-add">Add reason</button>
      </div>
      <div id="reason-chips" style="display:flex;flex-wrap:wrap;gap:8px"></div>
    </div>`;

  c.exclusion_reasons = c.exclusion_reasons || [];
  const renderChips = () => {
    $('#reason-chips').innerHTML = c.exclusion_reasons.length
      ? c.exclusion_reasons.map((r, i) => `<span class="chip">${esc(r)}<button data-i="${i}">×</button></span>`).join('')
      : '<span class="hint">No reasons yet. The model will write free-text reasons.</span>';
    $$('#reason-chips .chip button').forEach(b => b.addEventListener('click', () => {
      c.exclusion_reasons.splice(Number(b.dataset.i), 1); renderChips(); save();
    }));
  };

  const collect = () => {
    const body = { project_id: S.currentId, exclusion_reasons: c.exclusion_reasons };
    $$('#view textarea[data-field]').forEach(t => body[t.dataset.field] = t.value);
    return body;
  };
  const setState = (txt, cls = '') => { const s = $('#crit-save'); if (s) s.className = 'save-state ' + cls, s.innerHTML = txt ? `<span class="dot"></span>${txt}` : ''; };
  const save = async () => {
    setState('Saving…', 'saving');
    try { await api('/api/criteria', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collect()) }); setState('Saved', 'saved'); }
    catch (e) { setState('Save failed', ''); toast(e.message, 'err'); }
  };
  const debSave = debounce(save, 700);
  $$('#view textarea[data-field]').forEach(t => t.addEventListener('input', () => { setState('Editing…'); debSave(); }));

  const addReason = () => {
    const v = $('#reason-input').value.trim();
    if (!v) return;
    if (!c.exclusion_reasons.includes(v)) c.exclusion_reasons.push(v);
    $('#reason-input').value = ''; renderChips(); save();
  };
  $('#reason-add').addEventListener('click', addReason);
  $('#reason-input').addEventListener('keydown', e => { if (e.key === 'Enter') addReason(); });
  renderChips();
}

/* ============================================================= 3. IMPORT */
let importFiles = [];
async function viewImport() {
  const host = $('#view');
  if (needProject(host)) return;
  host.innerHTML = `
    <div class="card">
      <p class="card-title">Import references</p>
      <p class="card-sub">Upload .ris and .txt (PubMed/MEDLINE) files. Format is auto-detected; the source database is inferred from the filename, so edit it before importing.</p>
      <input type="file" id="file-input" accept=".ris,.txt,.nbib" multiple hidden>
      <div class="dropzone" id="dropzone" role="button" tabindex="0">
        <div class="dz-ico"><svg viewBox="0 0 24 24"><path d="M12 16V4m0 0L8 8m4-4 4 4"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg></div>
        <strong>Drop reference files here</strong>
        <span class="hint">or click to browse: .ris, .txt, .nbib</span>
        <div class="hint" id="pick-hint" style="margin-top:8px"></div>
      </div>
      <div id="inspect-area" style="margin-top:14px"></div>
    </div>
    <div id="dedup-area"></div>
    <div id="review-area"></div>`;

  const dz = $('#dropzone');
  const input = $('#file-input');
  dz.addEventListener('click', () => input.click());
  dz.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', onPick);

  // drag & drop: only the events that matter, with a counter so nested
  // dragleave on child elements doesn't clear the highlight early.
  let depth = 0;
  dz.addEventListener('dragenter', e => { e.preventDefault(); depth++; dz.classList.add('over'); });
  dz.addEventListener('dragover', e => { e.preventDefault(); });
  dz.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; dz.classList.remove('over'); } });
  dz.addEventListener('drop', e => {
    e.preventDefault(); depth = 0; dz.classList.remove('over');
    const files = Array.from(e.dataTransfer?.files || []);
    if (files.length) onPick({ target: { files } });
  });
  await loadDedupSummary();
}

async function onPick(e) {
  importFiles = Array.from(e.target.files);
  if (!importFiles.length) return;
  $('#pick-hint').textContent = `${importFiles.length} file(s) selected`;
  const fd = new FormData();
  importFiles.forEach(f => fd.append('files', f));
  let res;
  try { res = await api('/api/import/inspect', { method: 'POST', body: fd }); }
  catch (err) { toast(err.message, 'err'); return; }
  const fmtSel = (v) => `<select data-fmt><option value="ris" ${v === 'ris' ? 'selected' : ''}>RIS</option><option value="medline" ${v === 'medline' ? 'selected' : ''}>MEDLINE</option></select>`;
  $('#inspect-area').innerHTML = `
    <div class="file-row file-head">
      <div>File</div><div>Format</div><div>Source database</div><div>Records</div></div>
    ${res.files.map((f, i) => `<div class="file-row" data-i="${i}">
      <div class="file-name">${esc(f.filename)}<small>${f.no_abstract} without abstract</small></div>
      <div>${fmtSel(f.detected_format)}</div>
      <div><input type="text" data-src value="${esc(f.inferred_source)}" placeholder="Label this source"></div>
      <div class="file-count">${f.record_count}</div>
    </div>`).join('')}
    <div style="margin-top:16px"><button class="btn primary" id="do-import">Import ${importFiles.length} file(s)</button>
    <span class="hint" id="import-status" style="margin-left:10px"></span></div>`;
  $('#do-import').addEventListener('click', doImport);
}

async function doImport() {
  const rows = $$('#inspect-area .file-row[data-i]');
  const fd = new FormData();
  fd.append('project_id', S.currentId);
  importFiles.forEach(f => fd.append('files', f));
  rows.forEach(r => {
    fd.append('sources', r.querySelector('[data-src]').value.trim());
    fd.append('formats', r.querySelector('[data-fmt]').value);
  });
  const btn = $('#do-import'); btn.disabled = true;
  $('#import-status').innerHTML = '<span class="spinner"></span> Importing & deduplicating…';
  try {
    const res = await api('/api/import/commit', { method: 'POST', body: fd });
    toast('Imported. Duplicates removed: ' + res.summary.duplicates_removed, 'ok');
    importFiles = []; $('#file-input').value = ''; $('#inspect-area').innerHTML = ''; $('#pick-hint').textContent = '';
    await loadDedupSummary();
  } catch (e) { toast(e.message, 'err'); btn.disabled = false; $('#import-status').textContent = ''; }
}

async function loadDedupSummary() {
  let s;
  try { s = await api('/api/import/summary?project_id=' + S.currentId); }
  catch { return; }
  const area = $('#dedup-area');
  if (!s.total_in) { area.innerHTML = ''; $('#review-area').innerHTML = ''; return; }
  const bySource = s.by_source.map(x => `<tr><td>${esc(x.source || 'unlabelled')}</td><td>${x.identified}</td><td>${x.kept}</td></tr>`).join('');
  area.innerHTML = `<div class="card">
    <div class="spread"><p class="card-title" style="margin:0">Deduplication summary</p>
      <button class="btn sm" id="rerun-dedup">Re-run dedup</button></div>
    <p class="card-sub">Counts for your PRISMA flow diagram.</p>
    <div class="stat-row">
      <div class="stat accent"><div class="n">${s.total_in}</div><div class="l">Records identified</div></div>
      <div class="stat"><div class="n">${s.duplicates_removed}</div><div class="l">Duplicates removed</div></div>
      <div class="stat inc"><div class="n">${s.unique_out}</div><div class="l">Unique records</div></div>
      <div class="stat may"><div class="n">${s.pending_review_count}</div><div class="l">Merges to review</div></div>
      <div class="stat exc"><div class="n">${s.no_abstract}</div><div class="l">No abstract</div></div>
    </div>
    <div class="hint" style="margin-top:12px">Removed by: ${['doi', 'pmid', 'fuzzy'].map(m => `${m.toUpperCase()} ${s.merges_by_method[m] || 0}`).join(' · ')}</div>
    <div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>Source database</th><th>Identified</th><th>Kept (unique)</th></tr></thead><tbody>${bySource}</tbody></table></div>
    <div class="row" style="margin-top:16px"><button class="btn danger sm" id="reset-import">Reset import (delete all records)</button></div>
  </div>`;
  $('#rerun-dedup').addEventListener('click', async () => { await api('/api/import/dedup?project_id=' + S.currentId, { method: 'POST' }); toast('Dedup re-run', 'ok'); loadDedupSummary(); });
  $('#reset-import').addEventListener('click', async () => {
    if (!confirm('Delete ALL imported records (and their screening results) for this project?')) return;
    await api('/api/import/reset?project_id=' + S.currentId, { method: 'POST' });
    toast('Import reset', 'ok'); loadDedupSummary();
  });
  animateStats($('#dedup-area'));
  await loadReviewQueue();
}

async function loadReviewQueue() {
  const area = $('#review-area');
  const d = await api('/api/import/review?project_id=' + S.currentId);
  if (!d.items.length) { area.innerHTML = ''; return; }
  const side = (r, role) => `<div class="merge-side"><div class="role">${role}</div>
    <div style="font-weight:550">${esc(r.title)}</div>
    <div class="hint" style="margin-top:4px">${esc(r.first_author || 'n.a.')} · ${esc(r.year || 'n.d.')} · ${esc(r.source_database || '')}</div></div>`;
  area.innerHTML = `<div class="card">
    <p class="card-title">Review these merges <span class="badge maybe">${d.items.length}</span></p>
    <p class="card-sub">Borderline fuzzy matches (similarity 0.88–0.93). Confirm to merge, or split to keep both as separate records.</p>
    ${d.items.map(it => `<div class="merge-item" data-log="${it.log_id}">
      <div class="spread"><span class="badge maybe">similarity ${pct(it.similarity)}</span></div>
      <div class="merge-pair">${side(it.keep, 'Keep')}${side(it.drop, 'Merge in / or split')}</div>
      <div class="row"><button class="btn sm primary" data-act="confirm">Confirm merge</button><button class="btn sm" data-act="split">Keep separate</button></div>
    </div>`).join('')}
  </div>`;
  $$('.merge-item', area).forEach(item => {
    const log = item.dataset.log;
    item.querySelector('[data-act=confirm]').addEventListener('click', async () => { await api(`/api/import/review/${log}/confirm`, { method: 'POST' }); toast('Merged', 'ok'); loadDedupSummary(); });
    item.querySelector('[data-act=split]').addEventListener('click', async () => { await api(`/api/import/review/${log}/split`, { method: 'POST' }); toast('Kept separate', 'ok'); loadDedupSummary(); });
  });
}

/* ============================================================= 4. SCREEN */
async function viewScreen() {
  const host = $('#view');
  if (needProject(host)) return;
  host.innerHTML = '<div class="card"><span class="spinner"></span> Loading status…</div>';
  let st;
  try { st = await api('/api/screen/status?project_id=' + S.currentId); }
  catch (e) { host.innerHTML = emptyState('Could not load screening status', e.message); return; }

  const warn = [];
  if (!st.api_key_set) warn.push('No API key set. Add one in <b>Settings</b>.');
  if (!st.has_criteria) warn.push('Criteria look empty. Fill them in under <b>Criteria</b>.');
  if (!st.total_unique) warn.push('No records imported yet. See <b>Import</b>.');

  host.innerHTML = `
    <div class="card">
      <div class="spread">
        <div><p class="card-title" style="margin:0">Ready to screen</p>
        <p class="card-sub" style="margin:4px 0 0">Model: <b>${esc(st.model)}</b> · Reason list: ${st.reason_list.length ? st.reason_list.length + ' categories' : 'free-text'}</p></div>
        <div style="text-align:right"><div class="stat bare"><div class="n" style="color:var(--accent)">${st.unscreened}</div><div class="l">unscreened of ${st.total_unique}</div></div></div>
      </div>
      ${warn.length ? `<div style="margin-top:14px" class="hint">⚠ ${warn.join(' &nbsp; ')}</div>` : ''}
    </div>

    <div class="card">
      <p class="card-title">Mode A · Test run</p>
      <p class="card-sub">Screen a small sample live to sanity-check your criteria before spending on the full set. Each record is screened independently.</p>
      <div class="row" style="align-items:flex-end">
        <label class="field" style="margin:0;max-width:140px"><span>Sample size</span><input id="sample-size" type="number" min="1" max="500" value="25"></label>
        <button class="btn primary" id="run-test" ${st.unscreened ? '' : 'disabled'}>Run test</button>
        <button class="btn" id="cancel-test" style="display:none">Stop</button>
      </div>
      <div id="test-progress" style="margin-top:16px"></div>
      <div id="test-results" style="margin-top:16px"></div>
    </div>

    <div class="card">
      <p class="card-title">Mode B · Full run (Message Batches)</p>
      <p class="card-sub">Submit all unscreened records via the async Batches API at 50% of the cost, returning within 24h (usually faster). You can close and reopen the app while it runs.</p>
      <div id="batch-panel"></div>
    </div>`;

  $('#run-test').addEventListener('click', startTest);
  $('#cancel-test').addEventListener('click', async () => { await api('/api/screen/test/cancel?project_id=' + S.currentId, { method: 'POST' }); });
  $('#sample-size').value = Math.min(25, st.unscreened || 25);
  renderBatchPanel(st.active_batch);
  if (st.test_running) pollTest();
}

function progressBar(done, total, label, live = false) {
  const p = total ? Math.round(done / total * 100) : 0;
  return `<div class="progress${live ? ' live' : ''}"><i style="width:${p}%"></i></div>
    <div class="progress-meta"><span>${label || ''}</span><span>${done} / ${total}</span></div>`;
}

async function startTest() {
  const n = Math.max(1, Number($('#sample-size').value) || 25);
  $('#run-test').disabled = true; $('#cancel-test').style.display = '';
  try {
    await api('/api/screen/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: S.currentId, sample_size: n }) });
    pollTest();
  } catch (e) { toast(e.message, 'err'); $('#run-test').disabled = false; $('#cancel-test').style.display = 'none'; }
}

function pollTest() {
  const tick = async () => {
    let p;
    try { p = await api('/api/screen/test/progress?project_id=' + S.currentId); }
    catch { return; }
    $('#test-progress').innerHTML = progressBar(p.done, p.total, p.running ? 'Screening…' : (p.error ? 'Error' : 'Complete'), p.running);
    if (p.results) renderTestResults(p.results);
    if (!p.running) {
      clearPollers();
      $('#run-test').disabled = false; $('#cancel-test').style.display = 'none';
      if (p.error) toast(p.error, 'err'); else toast('Test run complete', 'ok');
    }
  };
  tick();
  addPoller(setInterval(tick, 1200));
}

function decisionBadge(d) {
  const cls = { INCLUDE: 'include', EXCLUDE: 'exclude', MAYBE: 'maybe' }[d] || 'neutral';
  return `<span class="badge ${cls}">${esc(d || 'n/a')}</span>`;
}
function renderTestResults(rows) {
  if (!rows.length) { $('#test-results').innerHTML = ''; return; }
  $('#test-results').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Decision</th><th>Conf.</th><th>Title</th><th>Reason</th><th>Category</th><th>Tags</th></tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${decisionBadge(r.decision)}</td><td>${pct(r.confidence)}</td>
      <td class="title-cell"><div class="t-title">${esc(r.title)}</div></td>
      <td>${esc(r.reason || '')}</td><td>${esc(r.exclusion_reason_category || '')}</td>
      <td>${(r.tags || []).map(t => `<span class="badge neutral">${esc(t)}</span>`).join(' ')}</td>
    </tr>`).join('')}</tbody></table></div>`;
}

function renderBatchPanel(b) {
  const host = $('#batch-panel');
  if (!b) {
    host.innerHTML = `<button class="btn primary" id="submit-batch">Submit full batch</button>`;
    const btn = $('#submit-batch');
    if (btn) btn.addEventListener('click', async () => {
      btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Submitting…';
      try { const r = await api('/api/screen/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: S.currentId }) }); toast('Batch submitted: ' + r.count + ' records', 'ok'); viewScreen(); }
      catch (e) { toast(e.message, 'err'); btn.disabled = false; btn.textContent = 'Submit full batch'; }
    });
    return;
  }
  const done = b.result_count || 0, total = b.record_count || 0;
  const statusBadge = { in_progress: 'maybe', ended: 'include', canceled: 'neutral', error: 'exclude' }[b.status] || 'neutral';
  host.innerHTML = `
    <div class="spread"><span class="badge ${statusBadge}">${esc(b.status)}</span>
      <span class="hint">batch ${esc(b.batch_id || '')}</span></div>
    <div style="margin-top:12px">${progressBar(done, total, b.status === 'in_progress' ? 'Processing on Anthropic…' : 'Results retrieved', b.status === 'in_progress')}</div>
    <div class="row" style="margin-top:14px">
      <button class="btn" id="refresh-batch">Refresh status</button>
      ${b.status === 'in_progress' ? '<button class="btn danger sm" id="cancel-batch">Cancel batch</button>' : ''}
      ${b.status === 'ended' ? '<button class="btn primary sm" onclick="go(\'results\')">View results</button>' : ''}
    </div>`;
  $('#refresh-batch').addEventListener('click', refreshBatch);
  const cb = $('#cancel-batch');
  if (cb) cb.addEventListener('click', async () => { await api('/api/screen/batch/cancel?project_id=' + S.currentId, { method: 'POST' }); toast('Cancel requested', 'ok'); refreshBatch(); });
  if (b.status === 'in_progress') { addPoller(setInterval(refreshBatch, 5000)); }
}
async function refreshBatch() {
  try { const st = await api('/api/screen/batch/status?project_id=' + S.currentId); clearPollers(); renderBatchPanel(st.active_batch); }
  catch (e) { /* keep polling */ }
}

/* ============================================================= 5. RESULTS */
async function viewResults() {
  const host = $('#view');
  if (needProject(host)) return;
  host.innerHTML = '<div class="card"><span class="spinner"></span> Loading results…</div>';
  let meta;
  try { meta = await api('/api/results/meta?project_id=' + S.currentId); }
  catch (e) { host.innerHTML = emptyState('Could not load results', e.message); return; }
  if (!meta.summary.total) { host.innerHTML = emptyState('No results yet', 'Screen some records under the Screen tab to see decisions here.'); return; }

  const sm = meta.summary;
  const catRows = Object.entries(sm.by_category || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join('');
  host.innerHTML = `
    <div class="card">
      <p class="card-title">Summary</p>
      <p class="card-sub">Decision counts for your PRISMA diagram.</p>
      <div class="stat-row">
        <div class="stat inc"><div class="n">${sm.INCLUDE || 0}</div><div class="l">Include</div></div>
        <div class="stat exc"><div class="n">${sm.EXCLUDE || 0}</div><div class="l">Exclude</div></div>
        <div class="stat may"><div class="n">${sm.MAYBE || 0}</div><div class="l">Maybe</div></div>
        <div class="stat accent"><div class="n">${sm.total || 0}</div><div class="l">Screened</div></div>
      </div>
      ${catRows ? `<div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>Reason category (exclude + maybe)</th><th>Count</th></tr></thead><tbody>${catRows}</tbody></table></div>` : ''}
    </div>
    <div class="card">
      <p class="card-title">Export</p>
      <p class="card-sub">RIS carries the included records into Covidence, Rayyan, or EndNote for full-text screening. CSV and PRISMA counts follow the filters below where applicable.</p>
      <div class="export-grid">
        <div class="export-opt">
          <div class="eo-head"><strong>RIS</strong><span class="badge accent">for full-text screening</span></div>
          <p class="hint">Records with their abstracts and the AI decision as a note.</p>
          <label class="field" style="max-width:230px;margin:10px 0"><span>Which decisions</span>
            <select id="ris-decisions">
              <option value="INCLUDE">Include only</option>
              <option value="INCLUDE,MAYBE">Include + Maybe</option>
              <option value="MAYBE">Maybe only</option>
              <option value="INCLUDE,EXCLUDE,MAYBE">All screened</option>
            </select></label>
          <button class="btn primary sm" id="export-ris">Download .ris</button>
        </div>
        <div class="export-opt">
          <div class="eo-head"><strong>CSV</strong></div>
          <p class="hint">The filtered result table as a spreadsheet.</p>
          <label class="check" style="margin:10px 0">
            <input type="checkbox" id="csv-abstracts">
            <span>Include abstract text</span>
          </label>
          <p class="hint" id="abs-warn" hidden>Abstracts from Embase and Scopus are licensed, so keep this file internal.</p>
          <button class="btn sm" id="export-csv" style="margin-top:10px">Download .csv</button>
        </div>
        <div class="export-opt">
          <div class="eo-head"><strong>PRISMA counts</strong></div>
          <p class="hint">Identified per database, duplicates removed, screened, excluded by reason, as stage/count rows.</p>
          <button class="btn sm" id="export-prisma" style="margin-top:10px">Download .csv</button>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="filters">
        <label class="field"><span>Decision</span><select id="f-decision"><option value="">All</option><option>INCLUDE</option><option>EXCLUDE</option><option>MAYBE</option></select></label>
        <label class="field"><span>Exclusion category</span><select id="f-category"><option value="">All</option>${(meta.categories || []).map(c => `<option>${esc(c)}</option>`).join('')}</select></label>
        <label class="field"><span>Tag</span><select id="f-tag"><option value="">All</option>${(meta.tags || []).map(t => `<option>${esc(t)}</option>`).join('')}</select></label>
        <label class="field"><span>Abstract</span><select id="f-abs"><option value="">All</option><option value="1">Has abstract</option><option value="0">No abstract</option></select></label>
        <button class="btn sm" id="apply-filters">Apply</button>
      </div>
      <div id="results-table"></div>
    </div>`;
  $('#export-csv').addEventListener('click', () => {
    const abs = $('#csv-abstracts').checked ? '&include_abstract=1' : '';
    window.location = '/api/results/export.csv?' + filterQS() + abs;
  });
  $('#csv-abstracts').addEventListener('change', e => { $('#abs-warn').hidden = !e.target.checked; });
  $('#export-ris').addEventListener('click', () => {
    const p = new URLSearchParams({ project_id: S.currentId, decisions: $('#ris-decisions').value });
    window.location = '/api/results/export.ris?' + p.toString();
  });
  $('#export-prisma').addEventListener('click', () => {
    window.location = '/api/results/prisma.csv?project_id=' + S.currentId;
  });
  $('#apply-filters').addEventListener('click', loadResultsTable);
  $$('#view .filters select').forEach(s => s.addEventListener('change', loadResultsTable));
  loadResultsTable();
}
function filterQS() {
  const p = new URLSearchParams({ project_id: S.currentId });
  const d = $('#f-decision')?.value, c = $('#f-category')?.value, t = $('#f-tag')?.value, a = $('#f-abs')?.value;
  if (d) p.set('decision', d); if (c) p.set('category', c); if (t) p.set('tag', t); if (a !== '') p.set('has_abstract', a);
  return p.toString();
}
async function loadResultsTable() {
  const d = await api('/api/results?' + filterQS());
  const host = $('#results-table');
  if (!d.rows.length) { host.innerHTML = '<div class="empty"><p class="muted">No records match these filters.</p></div>'; return; }
  host.innerHTML = `<div class="hint" style="margin-bottom:8px">${d.rows.length} record${d.rows.length === 1 ? '' : 's'}</div>
  <div class="table-wrap"><table class="results-table"><thead><tr>
    <th class="c-dec">Decision</th><th class="c-conf">Conf.</th><th class="c-title">Title</th>
    <th class="c-year">Year</th><th class="c-src">Sources</th><th class="c-reason">Reason</th>
    <th class="c-cat">Category</th><th class="c-tags">Tags</th><th class="c-doi">DOI</th>
    <th class="c-pmid">PMID</th><th class="c-abs">Abs.</th>
  </tr></thead><tbody>${d.rows.map(r => `<tr>
    <td class="c-dec">${decisionBadge(r.decision)}</td>
    <td class="c-conf">${pct(r.confidence)}</td>
    <td class="c-title"><div class="t-title">${esc(r.title)}</div><div class="t-meta">${esc(r.first_author || '')}</div></td>
    <td class="c-year">${esc(r.year || '')}</td>
    <td class="c-src"><div class="cell-stack">${(r.source_databases || []).map(s => `<span class="badge neutral">${esc(s)}</span>`).join('')}</div></td>
    <td class="c-reason">${esc(r.reason || '')}</td>
    <td class="c-cat">${esc(r.exclusion_reason_category || '')}</td>
    <td class="c-tags"><div class="cell-stack">${(r.tags || []).map(t => `<span class="badge neutral">${esc(t)}</span>`).join('')}</div></td>
    <td class="c-doi">${r.doi ? `<a href="https://doi.org/${esc(r.doi)}" target="_blank" rel="noopener">link</a>` : ''}</td>
    <td class="c-pmid">${esc(r.pmid || '')}</td>
    <td class="c-abs">${r.has_abstract ? 'yes' : 'no'}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

/* ============================================================= 6. SETTINGS */
async function viewSettings() {
  const host = $('#view');
  let s;
  try { s = await api('/api/settings'); }
  catch (e) { host.innerHTML = emptyState('Could not load settings', e.message); return; }
  host.innerHTML = `
    <div class="card" style="max-width:680px">
      <p class="card-title">Anthropic API key</p>
      <p class="card-sub">Stored locally in <code>secrets.local.json</code> (gitignored), never shown in full. This key is separate from any Claude Code / Claude.ai login.</p>
      <div class="key-row" style="margin-bottom:12px">
        ${s.api_key_set ? `<span class="key-mask">${esc(s.api_key_masked)}</span><span class="badge include">set</span>` : '<span class="badge neutral">not set</span>'}
      </div>
      <div class="row" style="align-items:flex-end">
        <label class="field" style="margin:0;flex:1"><span>${s.api_key_set ? 'Replace key' : 'Paste key'}</span><input id="api-key" type="password" placeholder="sk-ant-…"></label>
        <button class="btn primary" id="save-key">Save key</button>
        ${s.api_key_set ? '<button class="btn danger" id="remove-key">Remove</button>' : ''}
      </div>
    </div>
    <div class="card" style="max-width:680px">
      <p class="card-title">Model</p>
      <p class="card-sub">Chosen per request; independent of the key. Prompt caching + the batch discount apply automatically.</p>
      <label class="field" style="max-width:360px"><span>Default model</span>
        <select id="model-sel">${s.models.map(m => `<option value="${esc(m.id)}" ${m.id === s.model ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select></label>
      <button class="btn" id="save-model">Save model</button>
    </div>
    <div class="card" style="max-width:680px">
      <p class="card-title">Test connection</p>
      <p class="card-sub">Makes one tiny API call to confirm the key and selected model work.</p>
      <button class="btn primary" id="test-conn">Test connection</button>
      <div id="test-out" style="margin-top:12px"></div>
    </div>`;

  $('#save-key').addEventListener('click', async () => {
    const k = $('#api-key').value.trim();
    if (!k) { toast('Paste a key first', 'err'); return; }
    await api('/api/settings/key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: k }) });
    toast('Key saved', 'ok'); viewSettings();
  });
  const rm = $('#remove-key');
  if (rm) rm.addEventListener('click', async () => { await api('/api/settings/key', { method: 'DELETE' }); toast('Key removed', 'ok'); viewSettings(); });
  $('#save-model').addEventListener('click', async () => {
    await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: $('#model-sel').value }) });
    toast('Model saved', 'ok');
  });
  $('#test-conn').addEventListener('click', async () => {
    const out = $('#test-out'); out.innerHTML = '<span class="spinner"></span> Testing…';
    try {
      const r = await api('/api/settings/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: $('#model-sel').value }) });
      out.innerHTML = r.ok ? `<span class="badge include">✓ Connected</span> <span class="hint">${esc(r.message)}</span>` : `<span class="badge exclude">✗ Failed</span> <span class="hint">${esc(r.message)}</span>`;
    } catch (e) { out.innerHTML = `<span class="badge exclude">✗ Failed</span> <span class="hint">${esc(e.message)}</span>`; }
  });
}

boot();
