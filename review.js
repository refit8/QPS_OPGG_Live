/* ══════════════════════════════════════════════════════════════
   REVIEW MODE — offline reviewer edits for the OPGG-BRI portal

   Now built into the live portal (no review-config.js needed). Anyone can edit;
   nothing touches the real dataset. The owner merges with review_tool.py.

   - Register detail panel: quick edit of six fields. Asset Register > Edit Assets: every field.
   - Edits are kept in the reviewer's browser (localStorage) as an overlay on top of
     the data they were given, so nothing is lost on refresh.
   - "Export changes" writes a short changes file (old → new per field) that the
     project owner reviews with edit_assets.py → Review submissions.

   Hooks in app.js:  R8Review.applyToRaw(raw)  /  .decorate(idx)  /  .afterRender()
══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var CFG = window.R8_REVIEW || { enabled: true, baseVersion: 'live', assetsHash: null };
  if (!CFG.enabled) return;

  /* ── Editable fields (path inside assets.json → label / widget) ──
     quick: shown in the register detail panel.  sec: section on the Edit Assets page. */
  var PW_NOTES = [['retain','Retain'],['reuse','Reuse'],['adaptiveReuse','Adaptive Reuse'],['refurbish','Refurbish'],
    ['recycle','Recycle'],['disposal','Dispose'],['rehome','Rehome'],['remanufacture','Remanufacture'],['stewardship','Stewardship']];
  var CATEGORIES = ['Built Form', 'FF&E', 'Services', 'Construction Waste', 'Out-of-Scope'];
  var UNITS = ['Count', 'Mass (kg)', 'Area (m2)', 'Linear Metre (m)', 'Volume (m3)'];
  var FIELDS = [
    { key: 'title', ro: true,                         label: 'Title',                    type: 'text',     sec: 'Core details' },
    { key: 'category', ro: true,                      label: 'Category',                 type: 'select',   sec: 'Core details', opts: 'cats' },
    { key: 'unit', ro: true,                          label: 'Unit',                     type: 'select',   sec: 'Core details', opts: 'units' },
    { key: 'quantity',                      label: 'Quantity',                 type: 'number',   sec: 'Core details' },
    { key: 'location',                      label: 'Location',                 type: 'text',     sec: 'Core details' },
    { key: 'manufacturer',                  label: 'Manufacturer',             type: 'text',     sec: 'Core details', quick: true },
    { key: 'supplier',                      label: 'Supplier',                 type: 'text',     sec: 'Core details', quick: true },
    { key: 'primaryMaterialStream',         label: 'Primary material stream',  type: 'select',   sec: 'Core details', opts: 'mats' },
    { key: 'pathway.suggested',             label: 'Pathway',                  type: 'select',   sec: 'Pathway', opts: 'pathways', quick: true },
    { key: 'pathway.partners',              label: 'Primary partner(s)',       type: 'list',     sec: 'Pathway', quick: true,
      hint: 'Free text. Separate several with commas.' },
    { key: 'pathway.partnersSupplementary', label: 'Supplementary partner(s)', type: 'list',     sec: 'Pathway', quick: true,
      hint: 'Free text. Separate several with commas.' },
    { key: 'weight.perUnit',                label: 'Weight per unit (kg)',     type: 'number',   sec: 'Weight & dimensions' },
    { key: 'dimensions.height',             label: 'Height (mm)',              type: 'number',   sec: 'Weight & dimensions' },
    { key: 'dimensions.depth',              label: 'Depth (mm)',               type: 'number',   sec: 'Weight & dimensions' },
    { key: 'dimensions.width',              label: 'Width (mm)',               type: 'number',   sec: 'Weight & dimensions' },
    { key: 'embodiedCarbon.perUnit', ro: true,        label: 'EC per unit (kgCO₂e)', type: 'number',  sec: 'Environmental impact' },
    { key: 'embodiedCarbon.ecSource', ro: true,       label: 'EC source',                type: 'text',     sec: 'Environmental impact' },
    { key: 'wasteEmissions.factor', ro: true,         label: 'WE factor',                type: 'number',   sec: 'Environmental impact' },
    { key: 'wasteEmissions.efSource', ro: true,       label: 'EF source',                type: 'text',     sec: 'Environmental impact' },
    { key: 'notes.audit', ro: true,                   label: 'Audit notes',              type: 'textarea', sec: 'Notes' },
    { key: 'notes.workshop',                label: 'Workshop notes',           type: 'textarea', sec: 'Notes', quick: true }
  ].concat(PW_NOTES.map(function (n) {
    return { key: 'pathwayNotes.' + n[0], label: n[1], type: 'textarea', sec: 'Pathway notes' };
  }));
  var FIELD_BY_KEY = {};
  FIELDS.forEach(function (f) { FIELD_BY_KEY[f.key] = f; });

  /* Totals are calculated from the inputs, exactly as the owner's editor does (edit_assets.py recalc) */
  var CALCS = [
    { key: 'weight.total',            label: 'Total weight (kg)',          sec: 'Weight & dimensions', d: 2 },
    { key: 'embodiedCarbon.total',    label: 'EC total (kgCO₂e)',    sec: 'Environmental impact', d: 2 },
    { key: 'wasteEmissions.potential', label: 'WE potential (kgCO₂e)', sec: 'Environmental impact', d: 4 }
  ];
  var INPUT_OF_TOTALS = { 'quantity': 1, 'weight.perUnit': 1, 'embodiedCarbon.perUnit': 1, 'wasteEmissions.factor': 1 };
  function recalcTotals(r) {
    var q = Number(r.quantity) || 0, wp = Number(getPath(r, 'weight.perUnit')) || 0,
        ep = Number(getPath(r, 'embodiedCarbon.perUnit')) || 0, wf = Number(getPath(r, 'wasteEmissions.factor')) || 0;
    var wt = q * wp;
    setPath(r, 'weight.total', wt ? +wt.toFixed(4) : null);
    setPath(r, 'embodiedCarbon.total', q * ep ? +(q * ep).toFixed(4) : null);
    setPath(r, 'wasteEmissions.potential', wf * wt ? +(wf * wt).toFixed(6) : null);
  }

  /* app.js declares ASSETS / PW with let/const, so they are globals but NOT window properties */
  function assetsList() { return (typeof ASSETS !== 'undefined') ? ASSETS : null; }
  function pathwayNames() { return (typeof PW !== 'undefined') ? Object.keys(PW) : []; }

  /* Starred assets live in app.js (global `starred` Set, persisted by app.js). Reviewers' stars go into the export so
     the project owner can see which items they want quantities double-checked on. */
  function starList() {
    if (typeof starred === 'undefined') return [];
    var out = [];
    starred.forEach(function (id) { if (base[id]) out.push({ id: id, title: titles[id] }); });
    return out.sort(function (a, b) { return (a.title || '').localeCompare(b.title || ''); });
  }

  /* ── helpers ── */
  function clone(x) { return x === undefined ? undefined : JSON.parse(JSON.stringify(x)); }
  function same(a, b) { return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function getPath(o, path) {
    var p = path.split('.'), v = o;
    for (var i = 0; i < p.length; i++) { if (v == null) return null; v = v[p[i]]; }
    return v === undefined ? null : v;
  }
  function setPath(o, path, val) {
    var p = path.split('.'), t = o;
    for (var i = 0; i < p.length - 1; i++) {
      if (t[p[i]] == null || typeof t[p[i]] !== 'object') t[p[i]] = {};
      t = t[p[i]];
    }
    t[p[p.length - 1]] = val;
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function stamp(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + '_' + pad(d.getHours()) + pad(d.getMinutes());
  }
  /* Normalise what a reviewer typed into the shape stored in assets.json */
  function fromInput(f, raw) {
    if (f.type === 'list') {
      var seen = {}, out = [];
      String(raw).split(/[,\n;]+/).forEach(function (s) {
        s = s.trim();
        if (s && !seen[s.toLowerCase()]) { seen[s.toLowerCase()] = 1; out.push(s); }
      });
      return out;
    }
    if (f.type === 'number') {
      var n = String(raw).trim();
      return (n === '' || isNaN(Number(n))) ? null : Number(n);
    }
    var t = String(raw).trim();
    return t === '' ? null : (f.type === 'textarea' ? String(raw).replace(/\s+$/, '') : t);
  }
  function toInput(f, val) {
    if (f.type === 'list') return (val || []).join(', ');
    return val == null ? '' : String(val);
  }
  function show(f, val) {          // short human display for "Original: …"
    if (f.type === 'list') return (val && val.length) ? val.join(', ') : '(none)';
    if (val == null || val === '') return '(blank)';
    var s = String(val);
    return s.length > 90 ? s.slice(0, 90) + '…' : s;
  }

  /* ── state ── */
  var base = {};       // id → { path: original value }
  var titles = {};     // id → asset title (for the export)
  var raws = {};       // id → the raw assets.json record, with edits applied
  var origTotals = {}; // id → original calculated totals
  var overlay = { edits: {} };   // id → { path: edited value }   (only where different from base)
  var meta = { lastExportSig: null, lastExportAt: null, submitted: {} };
  var storeKey = 'r8-review:' + CFG.baseVersion + ':' + (CFG.assetsHash || '');
  var storageOk = true;

  function loadStore() {
    try {
      var s = JSON.parse(localStorage.getItem(storeKey));
      if (s && s.edits) overlay = { edits: s.edits };
      if (s && s.meta) meta = s.meta;
    } catch (e) { storageOk = false; }
    if (!meta.submitted) meta.submitted = {};
  }
  function saveStore() {
    try { localStorage.setItem(storeKey, JSON.stringify({ edits: overlay.edits, meta: meta })); storageOk = true; }
    catch (e) { storageOk = false; }
  }
  function sig() { return JSON.stringify([overlay.edits, starList().map(function (s) { return s.id; }).sort()]); }
  function counts() {
    var assets = 0, fields = 0;
    Object.keys(overlay.edits).forEach(function (id) {
      var n = Object.keys(overlay.edits[id]).length;
      if (n) { assets++; fields += n; }
    });
    return { assets: assets, fields: fields, stars: starList().length };
  }
  function unexported() { var c = counts(); return (c.fields > 0 || c.stars > 0) && sig() !== meta.lastExportSig; }

  function currentVal(id, path) {
    var e = overlay.edits[id];
    return (e && Object.prototype.hasOwnProperty.call(e, path)) ? e[path] : base[id][path];
  }
  function setEdit(id, path, val) {
    var b = base[id][path];
    if (same(val, b)) {
      if (overlay.edits[id]) { delete overlay.edits[id][path]; if (!Object.keys(overlay.edits[id]).length) delete overlay.edits[id]; }
    } else {
      (overlay.edits[id] = overlay.edits[id] || {})[path] = clone(val);
    }
    saveStore();
    if (raws[id]) setPath(raws[id], path, clone(currentVal(id, path)));
    syncAsset(id);
    updateBar();
  }

  /* ══ Drafts: what is typed in a form but not yet saved. Save commits them (setEdit); nothing else changes until then. ══ */
  var drafts = {};   // id → { path: value }
  function draftCount(id) { return Object.keys(drafts[id] || {}).length; }
  function allDrafts() {
    var a = 0, f = 0;
    Object.keys(drafts).forEach(function (id) { var n = draftCount(id); if (n) { a++; f += n; } });
    return { assets: a, fields: f };
  }
  function hasDraft(id, path) { return !!drafts[id] && Object.prototype.hasOwnProperty.call(drafts[id], path); }
  function formVal(id, path) { return hasDraft(id, path) ? drafts[id][path] : currentVal(id, path); }
  function setDraft(id, path, val) {
    if (same(val, currentVal(id, path))) { if (drafts[id]) delete drafts[id][path]; }
    else (drafts[id] = drafts[id] || {})[path] = clone(val);
    if (drafts[id] && !Object.keys(drafts[id]).length) delete drafts[id];
  }
  function saveDrafts(ids) {
    ids = ids || Object.keys(drafts);
    var n = 0;
    ids.forEach(function (id) {
      var d = drafts[id]; if (!d) return;
      Object.keys(d).forEach(function (p) { setEdit(id, p, d[p]); n++; });
      delete drafts[id];
    });
    if (n) { syncViews(); toast(n + ' change' + (n > 1 ? 's' : '') + ' saved'); }
    updateSaveBars();
    return n;
  }
  function discardDrafts(ids) { (ids || Object.keys(drafts)).forEach(function (id) { delete drafts[id]; }); updateSaveBars(); }
  /* Calculated cells shown while typing (preview only; committed on Save) */
  function previewRaw(id) {
    var t = clone(raws[id]), d = drafts[id] || {};
    Object.keys(d).forEach(function (p) { setPath(t, p, clone(d[p])); });
    if (Object.keys(d).concat(Object.keys(overlay.edits[id] || {})).some(function (k) { return INPUT_OF_TOTALS[k]; })) recalcTotals(t);
    return t;
  }

  /* Save bar (one per open form) */
  function saveBarHtml(id, withClear) {
    return '<div class="r8-savebar" data-id="' + id + '"><span class="r8-sb-msg"></span>' +
      '<button type="button" data-sb="discard">Discard</button><button type="button" data-sb="save" class="r8-sb-save">Save changes</button>' +
      (withClear ? '<button type="button" data-sb="clear" class="r8-sb-clear" title="Remove all your edits and restore the original data">Clear all changes</button>' : '') + '</div>';
  }
  /* Saved edits not yet submitted for review (submission is local for now; the server will receive it later) */
  function unsubmitted() {
    var a = 0, f = 0;
    Object.keys(overlay.edits).forEach(function (id) {
      var sv = (meta.submitted || {})[id], n = 0;
      Object.keys(overlay.edits[id]).forEach(function (p) {
        if (!sv || !Object.prototype.hasOwnProperty.call(sv, p) || !same(sv[p], overlay.edits[id][p])) n++;
      });
      if (n) { a++; f += n; }
    });
    return { assets: a, fields: f };
  }
  function plural(n, w) { return n + ' ' + w + (n > 1 ? 's' : ''); }
  function updateSaveBars() {
    var t = allDrafts(), u = unsubmitted();
    Array.prototype.forEach.call(document.querySelectorAll('.r8-savebar'), function (el) {
      var ready = u.fields > 0 && !t.fields;
      el.classList.toggle('r8-dirty', t.fields > 0);
      el.classList.toggle('r8-ready', ready);
      el.querySelector('.r8-sb-msg').textContent = t.fields
        ? plural(t.fields, 'unsaved change') + ' on ' + plural(t.assets, 'asset')
        : u.fields ? plural(u.fields, 'saved change') + ' on ' + plural(u.assets, 'asset') + ' — press Submit changes (top right) when you have finished all your edits'
        : counts().fields ? 'All changes submitted for review' : 'No changes';
      el.querySelector('[data-sb=save]').disabled = !t.fields;
      el.querySelector('[data-sb=discard]').disabled = !t.fields;
      var cb = el.querySelector('[data-sb=clear]');
      if (cb) cb.disabled = !(t.fields || counts().fields);
    });
    /* Header "Submit changes" button: appears after the first edit; greyed until staged edits are saved, then orange */
    var hb = document.getElementById('btn-submit-changes');
    if (hb) {
      var any = t.fields + counts().fields > 0;     // visible from the first edit; greyed whenever there is nothing to submit
      hb.hidden = !any;
      hb.classList.toggle('is-ready', u.fields > 0 && !t.fields);
      hb.setAttribute('aria-disabled', (u.fields > 0 && !t.fields) ? 'false' : 'true');
      hb.title = t.fields ? 'Save your changes before submitting' : (u.fields ? 'Submit your saved changes for review' : 'All saved changes have been submitted');
    }
  }
  function submitClick() {
    if (allDrafts().fields) { toast('Save changes before submitting', true); return; }
    if (!unsubmitted().fields) { toast('Nothing new to submit', true); return; }
    submitAll();
  }
  function submitAll() {
    var t = allDrafts(), u = unsubmitted();
    if (t.fields || !u.fields) return;
    if (!confirm('Submit ' + plural(u.fields, 'change') + ' on ' + plural(u.assets, 'asset') + ' for review?\n\nAn admin will review each change and decide whether to apply it. (Preview: submissions are not sent to a server yet.)')) return;
    meta.submitted = {};
    Object.keys(overlay.edits).forEach(function (id) { meta.submitted[id] = clone(overlay.edits[id]); });
    meta.submittedAt = new Date().toISOString();
    saveStore();
    toast(plural(u.fields, 'change') + ' submitted for review');
    updateSaveBars();
  }
  /* Mark assets in the Edit Assets list that have staged (unsaved) changes */
  function markStaged(id) {
    var el = document.querySelector('#r8e-list .r8e-item[data-id="' + id + '"]');
    if (el) el.classList.toggle('staged', draftCount(id) > 0);
    markRegisterStaged(id);
  }
  /* Same marker on the register table row / card view */
  function markRegisterStaged(id) {
    var list = assetsList() || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) {
      ['tr', 'gc'].forEach(function (p) { var e = document.getElementById(p + i); if (e) e.classList.toggle('r8-staged', draftCount(id) > 0); });
      break;
    }
  }
  function afterDraftAction(id) {
    var card = document.getElementById('r8-card');
    if (editBuilt && document.getElementById('tab-edit') && document.getElementById('tab-edit').style.display !== 'none') { renderEditList(); renderEditForm(); }
    else if (card) { var list = assetsList() || []; for (var i = 0; i < list.length; i++) if (list[i].id === id) { refresh(i); break; } }
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-sb]');
    if (!b) return;
    var id = b.closest('.r8-savebar').getAttribute('data-id');
    if (b.getAttribute('data-sb') === 'clear') { clearAll(); return; }
    if (b.getAttribute('data-sb') === 'save') saveDrafts();
    else {
      var t = allDrafts();
      if (!confirm('Discard all ' + t.fields + ' unsaved change' + (t.fields > 1 ? 's' : '') + ' on ' + t.assets + ' asset' + (t.assets > 1 ? 's' : '') + '? Nothing has been saved yet, so they will be lost.')) return;
      discardDrafts();
    }
    afterDraftAction(id);
  });

  /* Unsaved-changes prompt: Save / Discard / Stay. Used when moving to another asset or page, and on sign out. */
  function guard(proceed, what) {
    var t = allDrafts();
    if (!t.fields) return false;
    var m = document.createElement('div'); m.id = 'r8-modal';
    m.innerHTML = '<div class="r8-mbox"><h3>Unsaved changes</h3><p>You have ' + t.fields + ' unsaved change' + (t.fields > 1 ? 's' : '') +
      ' on ' + t.assets + ' asset' + (t.assets > 1 ? 's' : '') + '. Save them before ' + (what || 'continuing') + '?</p>' +
      '<div class="r8-mbtns"><button data-m="stay">Stay here</button><button data-m="discard">Discard</button><button data-m="save" class="r8-sb-save">Save and continue</button></div></div>';
    document.body.appendChild(m);
    m.addEventListener('click', function (e) {
      var k = e.target.getAttribute && e.target.getAttribute('data-m');
      if (!k) return;
      m.remove();
      if (k === 'stay') return;
      if (k === 'save') saveDrafts(); else discardDrafts();
      afterDraftAction(editSel);
      proceed();
    });
    return true;
  }

  /* Recalculate totals + refresh the normalised record the portal draws from */
  function syncAsset(id) {
    var r = raws[id]; if (!r) return;
    var e = overlay.edits[id] || {}, inputs = Object.keys(e).some(function (k) { return INPUT_OF_TOTALS[k]; });
    if (inputs) recalcTotals(r);
    else ['weight.total', 'embodiedCarbon.total', 'wasteEmissions.potential'].forEach(function (k) { setPath(r, k, origTotals[id][k]); });
    var list = assetsList();
    if (list && typeof normaliseAsset === 'function') {
      for (var i = 0; i < list.length; i++) if (list[i].id === id) { Object.assign(list[i], normaliseAsset(clone(r))); break; }
    }
    viewsDirty = true;
  }
  var viewsDirty = false;
  /* Redraw register, KPIs and home figures after edits (called when leaving the Edit Assets page) */
  function syncViews() {
    if (!viewsDirty) return;
    viewsDirty = false;
    ['initOverviewStats', 'initHomeStats', 'initRegisterKPIs', 'renderSpotlight', 'doFilter'].forEach(function (fn) {
      try { if (typeof window[fn] === 'function') window[fn](); } catch (e) { /* non-critical */ }
    });
  }

  /* ══ Hook 1: capture originals, then lay the reviewer's edits over the raw data ══ */
  function applyToRaw(raw) {
    loadStore();
    var ids = {};
    raw.forEach(function (r) {
      ids[r.id] = 1;
      titles[r.id] = r.title;
      raws[r.id] = r;
      origTotals[r.id] = {};
      ['weight.total', 'embodiedCarbon.total', 'wasteEmissions.potential'].forEach(function (k) { origTotals[r.id][k] = clone(getPath(r, k)); });
      base[r.id] = {};
      FIELDS.forEach(function (f) { base[r.id][f.key] = clone(getPath(r, f.key)); });
    });
    /* drop edits for assets that are gone, and edits the owner has since merged (now equal to the data) */
    Object.keys(overlay.edits).forEach(function (id) {
      if (!ids[id]) { delete overlay.edits[id]; return; }
      Object.keys(overlay.edits[id]).forEach(function (p) {
        if (!FIELD_BY_KEY[p] || FIELD_BY_KEY[p].ro || same(overlay.edits[id][p], base[id][p])) delete overlay.edits[id][p];
      });
      if (!Object.keys(overlay.edits[id]).length) delete overlay.edits[id];
    });
    saveStore();
    raw.forEach(function (r) {
      var e = overlay.edits[r.id];
      if (e) {
        Object.keys(e).forEach(function (p) { setPath(r, p, clone(e[p])); });
        if (Object.keys(e).some(function (k) { return INPUT_OF_TOTALS[k]; })) recalcTotals(r);
      }
    });
    updateBar();
  }

  /* ══ Hook 2: the review card inside the asset detail panel ══ */
  function fieldId(k, pfx) { return (pfx || 'r8f-') + k.replace(/\./g, '-'); }
  var openId = null;     // id of the asset whose review box is expanded (none by default)

  function cardHtml(a) {
    var id = a.id, rows = '';
    FIELDS.filter(function (f) { return !f.ro; }).forEach(function (f) {
      rows += rowHtml(id, f);
    });
    var n = Object.keys(overlay.edits[id] || {}).length;
    return '<div class="r8-card" id="r8-card" data-id="' + id + '">' +
      '<div class="r8-card-hd"><span>Review edits</span><span><span class="r8-badge" id="r8-asset-badge"' + (n ? '' : ' hidden') + '>' +
      n + ' edited</span> <a href="#" id="r8-close" class="r8-close">Close</a></span></div>' + saveBarHtml(id) + rows + saveBarHtml(id) +
      '<div class="r8-foot">Your edits are staged until you press <b>Save changes</b> (which applies every staged edit) or <b>Discard</b>. Saved changes are kept in this browser only; the project owner reviews them before anything changes in the main data.</div></div>';
  }

  function optsFor(f) {
    if (f.opts === 'pathways') return pathwayNames();
    if (f.opts === 'cats') return CATEGORIES.slice();
    if (f.opts === 'units') return UNITS.slice();
    var m = {};
    (assetsList() || []).forEach(function (a) { if (a.mat) m[a.mat] = 1; });
    return Object.keys(m).sort();
  }
  function rowHtml(id, f, pfx) {
    var rows = '';
    {
      var val = f.ro ? currentVal(id, f.key) : formVal(id, f.key), fid = fieldId(f.key, pfx), w = '';
      var changed = !same(val, base[id][f.key]);
      if (f.ro) {
        return '<div class="r8-row r8-ro-row"><label>' + f.label + '</label>' +
          '<div class="r8-ro">' + (val == null || val === '' ? '—' : esc(toInput(f, val))) + '</div></div>';
      }
      if (f.type === 'select') {
        var opts = optsFor(f);
        if (val && opts.indexOf(val) < 0) opts.push(val);
        w = '<select id="' + fid + '" data-key="' + f.key + '"><option value="">— none —</option>' +
          opts.map(function (o) { return '<option' + (o === val ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select>';
      } else if (f.type === 'textarea') {
        w = '<textarea id="' + fid + '" data-key="' + f.key + '" rows="4">' + esc(toInput(f, val)) + '</textarea>';
      } else if (f.type === 'number') {
        w = '<input id="' + fid + '" data-key="' + f.key + '" type="number" step="any" value="' + esc(toInput(f, val)) + '" autocomplete="off">';
      } else {
        w = '<input id="' + fid + '" data-key="' + f.key + '" type="text" value="' + esc(toInput(f, val)) + '" autocomplete="off">';
      }
      rows += '<div class="r8-row' + (changed ? ' r8-changed' : '') + '" data-row="' + f.key + '">' +
        '<label for="' + fid + '">' + f.label + '</label>' + w +
        (f.hint ? '<div class="r8-hint">' + f.hint + '</div>' : '') +
        '<div class="r8-orig"' + (changed ? '' : ' hidden') + '>Original: <span>' + esc(show(f, base[id][f.key])) +
        '</span> · <a href="#" data-revert="' + f.key + '">Revert</a></div></div>';
    }
    return rows;
  }

  function decorate(idx) {
    var list = assetsList(), a = list && list[idx];
    var host = document.getElementById('detailInner');
    if (!a || !host || !base[a.id]) return;
    if (openId && openId !== a.id) openId = null;      // opened box belongs to one asset at a time
    if (openId !== a.id) {
      // collapsed: just a button at the bottom of the detail panel
      var n0 = Object.keys(overlay.edits[a.id] || {}).length;
      host.insertAdjacentHTML('beforeend', '<div class="r8-open-wrap"><button type="button" id="r8-open">✎ Review / edit this asset' +
        (n0 ? ' <span class="r8-badge">' + n0 + ' edited</span>' : '') + '</button></div>');
      document.getElementById('r8-open').addEventListener('click', function () { openId = a.id; refresh(idx, null, true); });
      return;
    }
    host.insertAdjacentHTML('beforeend', cardHtml(a));
    var card = document.getElementById('r8-card');
    document.getElementById('r8-close').addEventListener('click', function (e) { e.preventDefault(); openId = null; refresh(idx); });

    updateSaveBars();
    function onEdit(e) {
      var el = e.target, key = el.getAttribute && el.getAttribute('data-key');
      if (!key) return;
      setDraft(a.id, key, fromInput(FIELD_BY_KEY[key], el.value));
      var row = el.closest('.r8-row'), ch = !same(formVal(a.id, key), base[a.id][key]);
      row.classList.toggle('r8-changed', ch);
      row.querySelector('.r8-orig').hidden = !ch;
      markStaged(a.id);
      updateSaveBars();
    }
    card.addEventListener('input', onEdit);
    card.addEventListener('change', onEdit);
    card.addEventListener('click', function (e) {
      var k = e.target.getAttribute && e.target.getAttribute('data-revert');
      if (!k) return;
      e.preventDefault();
      setDraft(a.id, k, clone(base[a.id][k]));
      refresh(idx);
    });
  }

  /* Re-render the detail panel + register (keeps scroll and focus) */
  function refresh(idx, focusId, toCard) {
    var sc = document.getElementById('p-detail'), top = sc ? sc.scrollTop : 0;
    if (typeof doFilter === 'function') doFilter();
    if (typeof selAsset === 'function') selAsset(idx);
    if (sc) sc.scrollTop = top;
    if (toCard) {
      var c = document.getElementById('r8-card');
      if (c) { c.scrollIntoView({ block: 'start' }); var f = c.querySelector('select,input,textarea'); if (f) f.focus({ preventScroll: true }); }
    }
    if (focusId) { var el = document.getElementById(focusId); if (el) el.focus(); }
  }

  /* ══ Hook 3: mark edited rows / cards in the register ══ */
  function afterRender() {
    Object.keys(drafts).forEach(markRegisterStaged);
    Object.keys(overlay.edits).forEach(function (id) {
      var list = assetsList();
      if (!Object.keys(overlay.edits[id]).length || !list) return;
      var idx = -1;
      for (var i = 0; i < list.length; i++) if (list[i].id === id) { idx = i; break; }
      ['tr', 'gc'].forEach(function (p) {
        var el = document.getElementById(p + idx); if (el) el.classList.add('r8-edited');
      });
    });
  }

  /* ══ Asset Register › Edit Assets: every field, one asset at a time ══ */
  var editSel = null, editQ = '', editBuilt = false, editSort = 'title';
  var SECTIONS = ['Core details', 'Pathway', 'Weight & dimensions', 'Environmental impact', 'Notes', 'Pathway notes'];

  function editedCount(id) { return Object.keys(overlay.edits[id] || {}).length; }
  function renderEditList() {
    var host = document.getElementById('r8e-list'), list = assetsList() || [];
    if (!host) return;
    var q = editQ.trim().toLowerCase();
    var rows = list.filter(function (a) {
      return !q || (a.n || '').toLowerCase().indexOf(q) >= 0 || (a.cat || '').toLowerCase().indexOf(q) >= 0 ||
        (a.mat || '').toLowerCase().indexOf(q) >= 0 || (a.pw || '').toLowerCase().indexOf(q) >= 0;
    });
    rows.sort(function (x, y) {
      var c = 0;
      if (typeof starFirst !== 'undefined' && starFirst && isStarred(x) !== isStarred(y)) return isStarred(x) ? -1 : 1;
      if (editSort === 'category') c = (x.cat || '').localeCompare(y.cat || '');
      else if (editSort === 'pathway') c = (x.pw || '').localeCompare(y.pw || '');
      return c || (x.n || '').localeCompare(y.n || '');
    });
    var sb = document.getElementById('r8e-starfirst');
    if (sb && typeof starFirst !== 'undefined') sb.classList.toggle('on', starFirst);
    host.innerHTML = rows.map(function (a, i) {
      var n = editedCount(a.id), nx = rows[i + 1];
      var end = (typeof starFirst !== 'undefined' && starFirst && isStarred(a) && nx && !isStarred(nx)) ? ' star-end' : '';
      return '<div class="r8e-item' + (a.id === editSel ? ' on' : '') + (n ? ' ed' : '') + (draftCount(a.id) ? ' staged' : '') + end + '" data-id="' + a.id + '">' +
        (a.thumbUrl || a.imageUrl ? '<img src="' + esc(a.thumbUrl || a.imageUrl) + '" loading="lazy" alt="">' : '<span class="r8e-ph"></span>') +
        '<span class="r8e-dot" title="Unsaved changes"></span>' +
        '<span class="r8e-it"><b>' + esc(a.n) + '</b><i>' + esc(a.cat) + (a.pw && a.pw !== 'Unknown' ? ' \u00b7 ' + esc(a.pw) : '') + '</i></span>' +
        (n ? '<span class="r8-badge">' + n + '</span>' : '') +
        (typeof starBtnHtml === 'function' ? starBtnHtml(a) : '') + '</div>';
    }).join('') || '<div class="r8e-empty">No assets match.</div>';
    document.getElementById('r8e-count').textContent = rows.length + ' of ' + list.length + ' assets';
  }
  function calcVal(id, c) {
    var v = getPath(raws[id] || {}, c.key);
    return v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: c.d });
  }
  function calcRows(id, sec) {
    return CALCS.filter(function (c) { return c.sec === sec; }).map(function (c) {
      return '<div class="r8-row r8-ro-row"><label>' + c.label + ' <span class="r8-auto">auto</span></label>' +
        '<div class="r8-ro r8-calc" data-calc="' + c.key + '">' + calcVal(id, c) + '</div></div>';
    }).join('');
  }
  function updateCalcs(id) {
    var t = previewRaw(id);
    CALCS.forEach(function (c) {
      var el = document.querySelector('#r8-edit-root [data-calc="' + c.key + '"]');
      if (el) { var v = getPath(t, c.key); el.textContent = v == null ? '\u2014' : Number(v).toLocaleString(undefined, { maximumFractionDigits: c.d }); }
    });
  }
  function renderEditForm() {
    var host = document.getElementById('r8e-main'), list = assetsList() || [], a = null;
    for (var i = 0; i < list.length; i++) if (list[i].id === editSel) { a = list[i]; break; }
    if (!host) return;
    if (!a) { host.innerHTML = '<div class="r8e-empty big">Pick an asset on the left to edit it.</div>'; return; }
    var n = editedCount(a.id), img = a.imageUrl;
    var html = saveBarHtml(a.id, true) + '<div class="r8e-head">' + (img ? '<img src="' + esc(img) + '" alt="">' : '<span class="r8e-ph big"></span>') +
      '<div><h2>' + esc(a.n) + '</h2><p>' + esc(a.cat) + ' \u00b7 ID ' + esc(a.id) + '</p></div>' +
      '<div class="r8e-head-act"><span class="r8-badge" id="r8e-badge"' + (n ? '' : ' hidden') + '>' + n + ' edited</span> ' +
      '<button type="button" id="r8e-revert-all"' + (n ? '' : ' disabled') + '>Revert this asset</button></div></div>';
    SECTIONS.forEach(function (sec) {
      var fs = FIELDS.filter(function (f) { return f.sec === sec; });
      html += '<div class="r8e-sec"><h3>' + sec + '</h3><div class="r8e-grid' + (sec === 'Notes' || sec === 'Pathway notes' ? ' one' : '') + '">' +
        fs.map(function (f) { return rowHtml(a.id, f, 'r8e-'); }).join('') + calcRows(a.id, sec) + '</div></div>';
    });
    html += '<div class="r8e-foot">Your edits are staged as you move between assets. Press <b>Save changes</b> to apply them all, or <b>Discard</b> to throw them away. Saved changes are kept in this browser only; the main dataset is not changed until the project owner reviews and accepts them. Photos can\u2019t be changed here yet.</div>';
    var sc = host.scrollTop;
    host.innerHTML = html;
    host.scrollTop = sc;
    updateSaveBars();
    updateCalcs(a.id);
  }
  function selectEdit(id) {
    editSel = id;
    renderEditList();
    var m = document.getElementById('r8e-main'); if (m) m.scrollTop = 0;
    renderEditForm();
  }
  function buildEditPage() {
    var root = document.getElementById('r8-edit-root');
    if (!root || editBuilt) return;
    editBuilt = true;
    root.innerHTML = '<div class="r8e-wrap"><aside class="r8e-side"><div class="r8e-sh"><h2>Edit Assets</h2>' +
      '<p>Changes are saved in your browser and sent to the project owner for approval.</p>' +
      '<div class="r8e-srch"><input type="search" id="r8e-q" placeholder="Search assets\u2026" autocomplete="off">' +
      '<button type="button" id="r8e-starfirst" class="star-btn" title="Show starred assets first">' + (typeof STAR_SVG !== 'undefined' ? STAR_SVG : '\u2605') + '</button></div>' +
      '<div class="r8e-srch"><label for="r8e-sort">Sort by</label><select id="r8e-sort"><option value="title">Title</option><option value="category">Category</option><option value="pathway">Pathway</option></select></div>' +
      '<div class="r8e-n" id="r8e-count"></div></div>' +
      '<div id="r8e-list" class="r8e-list"></div></aside><section id="r8e-main" class="r8e-main"></section></div>';
    document.getElementById('r8e-q').addEventListener('input', function (e) { editQ = e.target.value; renderEditList(); });
    document.getElementById('r8e-sort').addEventListener('change', function (e) { editSort = e.target.value; renderEditList(); });
    document.getElementById('r8e-starfirst').addEventListener('click', function () {
      if (typeof toggleStarFirst === 'function') toggleStarFirst();
      renderEditList();
    });
    document.getElementById('r8e-list').addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('.star-btn')) return;       // star button handles itself (app.js toggleStar)
      var it = e.target.closest && e.target.closest('.r8e-item'); if (!it) return;
      var id = it.getAttribute('data-id');
      if (id === editSel) return;
      selectEdit(id);       // staged changes stay staged while you move between assets
    });
    var main = document.getElementById('r8e-main');
    function onEdit(e) {
      var el = e.target, key = el.getAttribute && el.getAttribute('data-key');
      if (!key || !editSel) return;
      var f = FIELD_BY_KEY[key], v = fromInput(f, el.value);
      setDraft(editSel, key, v);
      var row = el.closest('.r8-row'), ch = !same(formVal(editSel, key), base[editSel][key]);
      row.classList.toggle('r8-changed', ch);
      row.querySelector('.r8-orig').hidden = !ch;
      updateCalcs(editSel);
      markStaged(editSel);
      updateSaveBars();
    }
    main.addEventListener('input', onEdit);
    main.addEventListener('change', onEdit);
    main.addEventListener('click', function (e) {
      var k = e.target.getAttribute && e.target.getAttribute('data-revert');
      if (k) { e.preventDefault(); setDraft(editSel, k, clone(base[editSel][k])); markStaged(editSel); renderEditForm(); return; }
      if (e.target.id === 'r8e-revert-all' && confirm('Revert every edit on this asset to the original values? (You still need to press Save changes.)')) {
        Object.keys(overlay.edits[editSel] || {}).concat(Object.keys(drafts[editSel] || {})).forEach(function (p) { setDraft(editSel, p, clone(base[editSel][p])); });
        markStaged(editSel); renderEditForm();
      }
    });
  }
  function openEditPage(id) {
    buildEditPage();
    var list = assetsList() || [];
    if (id) editSel = id;
    if (!editSel && list.length) editSel = list.slice().sort(function (x, y) { return (x.n || '').localeCompare(y.n || ''); })[0].id;
    if (typeof syncStarBtn === 'function') syncStarBtn();
    renderEditList();
    renderEditForm();
  }

  /* ══ Export / import / reset ══ */
  function buildExport() {
    var changes = [];
    Object.keys(overlay.edits).forEach(function (id) {
      Object.keys(overlay.edits[id]).forEach(function (path) {
        changes.push({ id: id, title: titles[id], field: path, old: clone(base[id][path]), 'new': clone(overlay.edits[id][path]) });
      });
    });
    changes.sort(function (x, y) { return (x.title || '').localeCompare(y.title || '') || x.field.localeCompare(y.field); });
    return {
      format: 'opgg-review-changes', version: 1,
      baseVersion: CFG.baseVersion, assetsHash: CFG.assetsHash || null,
      exportedAt: new Date().toISOString(), changes: changes,
      starred: starList()
    };
  }
  function markExported() { meta.lastExportSig = sig(); meta.lastExportAt = new Date().toISOString(); saveStore(); updateBar(); }

  function exportChanges() {
    var c = counts();
    if (!c.fields && !c.stars) { alert('There is nothing to export yet. Edit an asset or star one first.'); return; }
    var text = JSON.stringify(buildExport(), null, 2), name = 'review_' + stamp(new Date()) + '.json';
    function fallback() {
      var url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
      var a = document.createElement('a'); a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      markExported();
      toast('Saved to your Downloads folder as ' + name);
    }
    if (window.showSaveFilePicker) {
      window.showSaveFilePicker({ suggestedName: name, types: [{ description: 'Review changes', accept: { 'application/json': ['.json'] } }] })
        .then(function (h) { return h.createWritable().then(function (w) { return w.write(text).then(function () { return w.close(); }); }); })
        .then(function () { markExported(); toast('Changes exported'); })
        .catch(function (e) { if (e && e.name === 'AbortError') return; fallback(); });
    } else { fallback(); }
  }

  function importChanges(file) {
    var rd = new FileReader();
    rd.onload = function () {
      var j;
      try { j = JSON.parse(rd.result); } catch (e) { alert('That file is not valid JSON.'); return; }
      if (!j || j.format !== 'opgg-review-changes' || !Array.isArray(j.changes)) { alert('That is not a review changes file.'); return; }
      if (j.baseVersion !== CFG.baseVersion &&
          !confirm('This file was made from a different package version (' + j.baseVersion + ', this one is ' + CFG.baseVersion + '). Import anyway?')) return;
      var n = 0;
      j.changes.forEach(function (c) {
        if (!base[c.id] || !FIELD_BY_KEY[c.field]) return;
        if (same(c['new'], base[c.id][c.field])) return;
        (overlay.edits[c.id] = overlay.edits[c.id] || {})[c.field] = clone(c['new']); n++;
      });
      saveStore();
      var ns = 0;
      if (Array.isArray(j.starred) && typeof starred !== 'undefined') {
        j.starred.forEach(function (s) { if (s && base[s.id] && !starred.has(s.id)) { starred.add(s.id); ns++; } });
        try { localStorage.setItem(STAR_KEY, JSON.stringify(Array.from(starred))); } catch (e) { /* stars just will not persist */ }
      }
      alert(n + ' change(s)' + (ns ? ' and ' + ns + ' starred asset(s)' : '') + ' imported. The page will reload.');
      location.reload();
    };
    rd.readAsText(file);
  }

  /* Remove every saved and staged edit and put the original data back (no page reload, so you stay where you are) */
  function clearAll() {
    var t = allDrafts(), c = counts();
    if (!t.fields && !c.fields) return;
    var submittedNote = Object.keys(meta.submitted || {}).length ? '\n\nChanges you have already submitted for review are not affected.' : '';
    if (!confirm('Clear all changes?\n\nThis removes every edit you have saved or staged in this browser and restores the original data. This cannot be undone.' + submittedNote)) return;
    var ids = Object.keys(overlay.edits);
    ids.forEach(function (id) {
      Object.keys(overlay.edits[id]).forEach(function (p) { if (raws[id]) setPath(raws[id], p, clone(base[id][p])); });
    });
    overlay.edits = {}; drafts = {}; meta.submitted = {};
    saveStore();
    ids.forEach(syncAsset);
    syncViews();
    updateSaveBars();
    if (editBuilt) { renderEditList(); renderEditForm(); }
    var card = document.getElementById('r8-card');
    if (card) { var list = assetsList() || [], cid = card.getAttribute('data-id'); for (var i = 0; i < list.length; i++) if (list[i].id === cid) { refresh(i); break; } }
    toast('All changes cleared. Original data restored.');
  }

  function resetAll() {
    if (!counts().fields) return;
    if (!confirm('Discard ALL your edits in this browser and go back to the original data?\n\nExport first if you want to keep them.')) return;
    overlay = { edits: {} }; meta = { lastExportSig: null, lastExportAt: null };
    saveStore(); location.reload();
  }

  /* ══ Floating bar ══ */
  var barEl = null, toastEl = null, toastT = null;
  function toast(msg, warn) {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.hidden = false;
    toastEl.style.background = warn ? '#e8730c' : '';
    toastEl.style.bottom = warn ? '24px' : '';
    toastEl.style.top = warn ? 'auto' : '';
    toastEl.style.left = warn ? 'auto' : '';
    toastEl.style.right = warn ? '24px' : '';
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 3500);
  }
  function updateBar() {
    if (!barEl) return;
    var c = counts(), dirty = unexported();
    barEl.classList.toggle('r8-dirty', dirty);
    var parts = [];
    if (c.fields) parts.push(c.fields + ' change' + (c.fields > 1 ? 's' : '') + ' on ' + c.assets + ' asset' + (c.assets > 1 ? 's' : ''));
    if (c.stars) parts.push(c.stars + ' starred');
    barEl.querySelector('.r8-count').textContent = parts.join(' \u00b7 ') || 'No changes yet';
    var st = barEl.querySelector('.r8-state');
    st.textContent = !storageOk ? 'Browser storage unavailable — export before closing'
      : dirty ? 'Not exported yet'
      : meta.lastExportAt ? 'Last exported ' + new Date(meta.lastExportAt).toLocaleString() : '';
    barEl.querySelector('[data-act=export]').disabled = !(c.fields || c.stars);
    barEl.querySelector('[data-act=reset]').disabled = !c.fields;
  }
  /* Stars live in app.js (shared with the register); keep the Edit Assets list in step */
  function onStarChange() { if (editBuilt) renderEditList(); }
  function buildBar() {
    var css = document.createElement('style');
    css.textContent =
      '.r8e-srch{display:flex;gap:8px;align-items:center;margin-bottom:8px}.r8e-srch input{flex:1}.r8e-srch label{font-size:12px;color:var(--grey-500,#737373)}' +
      '.r8e-srch select{flex:1;font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--grey-300,#d4d4d4);border-radius:6px;background:#fff}' +
      '#r8e-starfirst{border:1px solid var(--grey-300,#d4d4d4);border-radius:6px;background:#fff;padding:7px;cursor:pointer;display:inline-flex}#r8e-starfirst.on{border-color:var(--orange,#e8730c);background:#fff4ec}#r8e-starfirst svg{width:16px;height:16px}#r8e-starfirst.on svg{fill:var(--orange,#e8730c);stroke:var(--orange,#e8730c)}' +
      'tr.r8-staged td:first-child{box-shadow:inset 3px 0 0 #f4b98a}tr.r8-staged td{background:#fffaf5}.g-card.r8-staged{box-shadow:inset 0 0 0 2px #f4b98a}' +
      '.r8e-dot{display:none;width:9px;height:9px;border-radius:50%;background:var(--orange,#e8730c);flex:0 0 auto}.r8e-item.staged .r8e-dot{display:block}.r8e-item.staged{background:#fffaf5}' +
      '.r8e-item .star-btn{margin-left:auto}.r8e-item:not(:hover) .star-btn:not(.on){visibility:hidden}.r8e-item.star-end{border-bottom:2px solid var(--orange,#e8730c)}' +
      '.r8-savebar{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:8px 12px;margin:0 0 12px;border:1px solid var(--grey-200,#e5e5e5);border-radius:8px;background:#fff;font-size:13px}' +
      '.r8-savebar .r8-sb-msg{margin-right:auto;color:var(--grey-500,#737373)}.r8-savebar.r8-dirty{border-color:var(--orange,#e8730c);background:#fff8f0}.r8-savebar.r8-dirty .r8-sb-msg{color:var(--orange,#e8730c);font-weight:600}' +
      '.r8-savebar button,#r8-modal button{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--grey-300,#d4d4d4);border-radius:6px;background:#fff;cursor:pointer}' +
      '.r8-savebar.r8-ready{border-color:var(--navy,#1e1b5c);background:#f3f2fb}.r8-savebar.r8-ready .r8-sb-msg{color:var(--navy,#1e1b5c);font-weight:600}' +
      '.r8-sb-clear{color:#b42318!important;border-color:#f3c4bf!important}.r8-sb-clear:hover:not(:disabled){background:#fef3f2!important}' +
      '.r8-savebar button:disabled{opacity:.4;cursor:default}.r8-sb-save{background:var(--orange,#e8730c)!important;border-color:var(--orange,#e8730c)!important;color:#fff;font-weight:700}.r8-sb-save:disabled{opacity:.4}' +
      '.r8e-main>.r8-savebar:first-child{position:sticky;top:-24px;z-index:5;margin:-24px -32px 16px;border-radius:0;border-width:0 0 1px}' +
      '#r8-modal{position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center}' +
      '.r8-mbox{background:#fff;border-radius:12px;padding:22px 24px;max-width:420px;width:calc(100vw - 32px);box-shadow:0 16px 40px rgba(0,0,0,.3)}.r8-mbox h3{margin:0 0 8px;font-size:18px}.r8-mbox p{margin:0 0 18px;font-size:14px;line-height:1.5;color:var(--grey-700,#404040)}' +
      '.r8-mbtns{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}' +
      '.r8e-wrap{display:flex;height:100%;min-height:0;background:var(--off-white,#fafafa)}' +
      '.r8e-side{width:330px;flex:0 0 330px;display:flex;flex-direction:column;background:#fff;border-right:1px solid var(--grey-200,#e5e5e5);min-height:0}' +
      '.r8e-sh{padding:16px 16px 10px;border-bottom:1px solid var(--grey-200,#e5e5e5)}.r8e-sh h2{font-size:18px;margin:0 0 4px}' +
      '.r8e-sh p{font-size:12px;color:var(--grey-500,#737373);margin:0 0 10px;line-height:1.4}' +
      '.r8e-sh input{width:100%;box-sizing:border-box;font:inherit;font-size:14px;padding:7px 10px;border:1px solid var(--grey-300,#d4d4d4);border-radius:6px}' +
      '.r8e-sh input:focus{outline:2px solid var(--orange,#e8730c);outline-offset:-1px}.r8e-n{font-size:11.5px;color:var(--grey-500,#737373);margin-top:6px}' +
      '.r8e-list{flex:1;overflow-y:auto}.r8e-item{display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;border-bottom:1px solid var(--grey-100,#f0f0f0)}' +
      '.r8e-item:hover{background:var(--off-white,#fafafa)}.r8e-item.on{background:#fff4ec;box-shadow:inset 3px 0 0 var(--orange,#e8730c)}' +
      '.r8e-item img,.r8e-ph{width:38px;height:38px;border-radius:5px;object-fit:cover;background:#eee;flex:0 0 auto}.r8e-ph.big{width:72px;height:72px;display:block}' +
      '.r8e-it{min-width:0;flex:1}.r8e-it b{display:block;font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.r8e-it i{font-style:normal;font-size:11.5px;color:var(--grey-500,#737373)}.r8e-empty{padding:24px;color:var(--grey-500,#737373);font-size:14px}.r8e-empty.big{text-align:center;margin-top:80px}' +
      '.r8e-main{flex:1;min-width:0;overflow-y:auto;padding:24px 32px 60px}' +
      '.r8e-head{display:flex;align-items:center;gap:16px;margin-bottom:18px}.r8e-head img{width:72px;height:72px;border-radius:8px;object-fit:cover}' +
      '.r8e-head h2{font-size:21px;margin:0 0 3px}.r8e-head p{margin:0;font-size:12px;color:var(--grey-500,#737373)}.r8e-head>div:nth-child(2){flex:1;min-width:0}' +
      '.r8e-head-act button{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--grey-300,#d4d4d4);border-radius:6px;background:#fff;cursor:pointer}.r8e-head-act button:disabled{opacity:.4;cursor:default}' +
      '.r8e-sec{background:#fff;border:1px solid var(--grey-200,#e5e5e5);border-radius:10px;padding:16px 20px;margin-bottom:14px}' +
      '.r8e-sec h3{margin:0 0 12px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--grey-500,#737373)}' +
      '.r8e-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 20px}.r8e-grid.one{grid-template-columns:1fr}' +
      '.r8e-calc{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:13px;background:#eef3ff;border-radius:6px;padding:8px 12px;margin-top:4px}.r8e-calc b{width:100%;font-size:11.5px;color:var(--grey-500,#737373)}.r8e-calc em{font-style:normal;font-weight:600}' +
      '.r8e-foot{font-size:12px;color:var(--grey-500,#737373);line-height:1.5;max-width:720px}' +
      '@media(max-width:900px){.r8e-wrap{flex-direction:column}.r8e-side{width:auto;flex:0 0 240px}.r8e-grid{grid-template-columns:1fr}.r8e-main{padding:16px}}' +
      '.r8-open-wrap{margin:16px 0 8px}.r8-open-wrap button{width:100%;font:inherit;font-size:14px;font-weight:600;padding:10px 14px;border-radius:8px;cursor:pointer;' +
      'background:#fff;color:var(--orange,#e8730c);border:1.5px dashed var(--orange,#e8730c)}.r8-open-wrap button:hover{background:#fff4ec}' +
      '.r8-close{font-size:12px;text-transform:none;letter-spacing:0;color:var(--grey-500,#737373);margin-left:8px}' +
      '.r8-card{margin:12px 0;padding:12px 14px;border:1.5px solid var(--orange,#e8730c);border-radius:8px;background:var(--off-white,#fafafa)}' +
      '.r8-card-hd{display:flex;justify-content:space-between;align-items:center;font-weight:700;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--orange,#e8730c);margin-bottom:8px}' +
      '.r8-badge{background:var(--orange,#e8730c);color:#fff;border-radius:10px;padding:1px 8px;font-size:11px;letter-spacing:0;text-transform:none}' +
      '.r8-row{margin-bottom:10px}.r8-row label{display:block;font-size:12px;font-weight:600;color:var(--grey-700,#404040);margin-bottom:3px}' +
      '.r8-row input,.r8-row select,.r8-row textarea{width:100%;box-sizing:border-box;font:inherit;font-size:14px;padding:6px 8px;border:1px solid var(--grey-300,#d4d4d4);border-radius:5px;background:#fff;color:inherit}' +
      '.r8-row textarea{resize:vertical;line-height:1.4}' +
      '.r8-row input:focus,.r8-row select:focus,.r8-row textarea:focus{outline:2px solid var(--orange,#e8730c);outline-offset:-1px}' +
      '.r8-changed input,.r8-changed select,.r8-changed textarea{border-color:var(--orange,#e8730c);background:#fff8f0}' +
      '.r8-ro{padding:6px 8px;border-radius:5px;background:var(--grey-100,#f3f3f3);color:var(--grey-700,#404040);font-size:14px;white-space:pre-wrap;min-height:20px}.r8-auto{font-weight:500;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--grey-500,#737373);margin-left:4px}.r8-ro.r8-calc{background:#eef3ff;color:#1e3a8a;font-weight:600}.r8-hint{font-size:11.5px;color:var(--grey-500,#737373);margin-top:2px}' +
      '.r8-orig{font-size:12px;color:var(--grey-500,#737373);margin-top:3px}.r8-orig a{color:var(--orange,#e8730c)}' +
      '.r8-foot{font-size:12px;color:var(--grey-500,#737373);border-top:1px solid var(--grey-200,#e5e5e5);padding-top:8px;margin-top:4px}' +
      'tr.r8-edited td:first-child{box-shadow:inset 3px 0 0 var(--orange,#e8730c)}.g-card.r8-edited{box-shadow:inset 0 0 0 2px var(--orange,#e8730c)}' +
      '#r8-bar{position:fixed;left:14px;bottom:14px;z-index:99999;display:flex;align-items:center;gap:10px;flex-wrap:wrap;max-width:calc(100vw - 28px);' +
      'background:#1a1a1a;color:#fff;border-radius:10px;padding:8px 12px;font:13px/1.3 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.35)}' +
      '#r8-bar.r8-dirty{outline:2px solid var(--orange,#e8730c)}' +
      '#r8-bar .r8-tag{color:var(--orange,#e8730c);font-weight:700;font-size:11px;letter-spacing:.06em}' +
      '#r8-bar .r8-state{opacity:.7;font-size:12px}' +
      '#r8-bar button{font:inherit;font-size:12.5px;border:0;border-radius:5px;padding:5px 10px;cursor:pointer;background:#3a3a3a;color:#fff}' +
      '#r8-bar button[data-act=export]{background:var(--orange,#e8730c);font-weight:700}#r8-bar button:disabled{opacity:.4;cursor:default}' +
      '#r8-toast{position:fixed;left:14px;bottom:66px;z-index:99999;background:#16a34a;color:#fff;border-radius:6px;padding:7px 12px;font:13px system-ui,sans-serif}';
    document.head.appendChild(css);

    toastEl = document.createElement('div'); toastEl.id = 'r8-toast'; toastEl.hidden = true; document.body.appendChild(toastEl);
    updateSaveBars();
    window.addEventListener('beforeunload', function (e) { if (allDrafts().fields) { e.preventDefault(); e.returnValue = ''; } });
    updateBar();
  }

  window.R8Review = { submitClick: submitClick, unsubmittedCount: function () { return unsubmitted().fields; }, guard: guard, hasDrafts: function () { return allDrafts().fields > 0; }, openEditPage: openEditPage, syncViews: syncViews, applyToRaw: applyToRaw, decorate: decorate, afterRender: afterRender, onStarChange: onStarChange, exportChanges: exportChanges, resetAll: resetAll, _buildExport: buildExport, _fields: FIELDS };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', buildBar); else buildBar();
})();
