/* ══════════════════════════════════════════════════════════════
   REVIEW MODE — offline reviewer edits for the OPGG-BRI portal

   Inert on the live site. It only activates when the review package
   defines window.R8_REVIEW (review-config.js, written by
   scripts/build_review_package.py).

   - Six fields are editable in the asset detail panel; everything else is read-only.
   - Edits are kept in the reviewer's browser (localStorage) as an overlay on top of
     the data they were given, so nothing is lost on refresh.
   - "Export changes" writes a short changes file (old → new per field) that the
     project owner reviews with edit_assets.py → Review submissions.

   Hooks in app.js:  R8Review.applyToRaw(raw)  /  .decorate(idx)  /  .afterRender()
══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var CFG = window.R8_REVIEW;
  if (!CFG || !CFG.enabled) return;

  /* ── Editable fields (path inside assets.json → label / widget) ── */
  var FIELDS = [
    { key: 'pathway.suggested',             label: 'Pathway',                  type: 'select' },
    { key: 'pathway.partners',              label: 'Primary partner(s)',       type: 'list',
      hint: 'Free text. Separate several with commas.' },
    { key: 'pathway.partnersSupplementary', label: 'Supplementary partner(s)', type: 'list',
      hint: 'Free text. Separate several with commas.' },
    { key: 'notes.workshop',                label: 'Workshop notes',           type: 'textarea' },
    { key: 'manufacturer',                  label: 'Manufacturer',             type: 'text' },
    { key: 'supplier',                      label: 'Supplier',                 type: 'text' }
  ];
  var FIELD_BY_KEY = {};
  FIELDS.forEach(function (f) { FIELD_BY_KEY[f.key] = f; });

  /* How an edited raw field maps onto the normalised ASSETS entry used by the portal */
  var LIVE = {
    'pathway.suggested':             function (a, v) { a.pw = v || 'Unknown'; },
    'pathway.partners':              function (a, v) { a.partners = v || []; },
    'pathway.partnersSupplementary': function (a, v) { a.partnersSupp = v || []; },
    'notes.workshop':                function (a, v) { a.workshop = v || null; },
    'manufacturer':                  function (a, v) { a.mfr = v || null; },
    'supplier':                      function (a, v) { a.sup = v || null; }
  };

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
  var overlay = { edits: {} };   // id → { path: edited value }   (only where different from base)
  var meta = { lastExportSig: null, lastExportAt: null };
  var storeKey = 'r8-review:' + CFG.baseVersion + ':' + (CFG.assetsHash || '');
  var storageOk = true;

  function loadStore() {
    try {
      var s = JSON.parse(localStorage.getItem(storeKey));
      if (s && s.edits) overlay = { edits: s.edits };
      if (s && s.meta) meta = s.meta;
    } catch (e) { storageOk = false; }
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
    // keep the normalised portal record in step
    var list = assetsList();
    if (list) {
      for (var i = 0; i < list.length; i++) if (list[i].id === id) { LIVE[path](list[i], clone(val)); break; }
    }
    updateBar();
  }

  /* ══ Hook 1: capture originals, then lay the reviewer's edits over the raw data ══ */
  function applyToRaw(raw) {
    loadStore();
    var ids = {};
    raw.forEach(function (r) {
      ids[r.id] = 1;
      titles[r.id] = r.title;
      base[r.id] = {};
      FIELDS.forEach(function (f) { base[r.id][f.key] = clone(getPath(r, f.key)); });
    });
    Object.keys(overlay.edits).forEach(function (id) { if (!ids[id]) delete overlay.edits[id]; });
    raw.forEach(function (r) {
      var e = overlay.edits[r.id];
      if (e) Object.keys(e).forEach(function (p) { if (FIELD_BY_KEY[p]) setPath(r, p, clone(e[p])); });
    });
    updateBar();
  }

  /* ══ Hook 2: the review card inside the asset detail panel ══ */
  function fieldId(k) { return 'r8f-' + k.replace(/\./g, '-'); }
  var openId = null;     // id of the asset whose review box is expanded (none by default)
  var dirtyIdx = null;   // asset whose read-only view needs a refresh once focus leaves the card

  function cardHtml(a) {
    var id = a.id, rows = '';
    FIELDS.forEach(function (f) {
      var val = currentVal(id, f.key), fid = fieldId(f.key), w = '';
      var changed = !same(val, base[id][f.key]);
      if (f.type === 'select') {
        var opts = pathwayNames();
        if (val && opts.indexOf(val) < 0) opts.push(val);
        w = '<select id="' + fid + '" data-key="' + f.key + '"><option value="">— none —</option>' +
          opts.map(function (o) { return '<option' + (o === val ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select>';
      } else if (f.type === 'textarea') {
        w = '<textarea id="' + fid + '" data-key="' + f.key + '" rows="4">' + esc(toInput(f, val)) + '</textarea>';
      } else {
        w = '<input id="' + fid + '" data-key="' + f.key + '" type="text" value="' + esc(toInput(f, val)) + '" autocomplete="off">';
      }
      rows += '<div class="r8-row' + (changed ? ' r8-changed' : '') + '" data-row="' + f.key + '">' +
        '<label for="' + fid + '">' + f.label + '</label>' + w +
        (f.hint ? '<div class="r8-hint">' + f.hint + '</div>' : '') +
        '<div class="r8-orig"' + (changed ? '' : ' hidden') + '>Original: <span>' + esc(show(f, base[id][f.key])) +
        '</span> · <a href="#" data-revert="' + f.key + '">Revert</a></div></div>';
    });
    var n = Object.keys(overlay.edits[id] || {}).length;
    return '<div class="r8-card" id="r8-card" data-id="' + id + '">' +
      '<div class="r8-card-hd"><span>Review edits</span><span><span class="r8-badge" id="r8-asset-badge"' + (n ? '' : ' hidden') + '>' +
      n + ' edited</span> <a href="#" id="r8-close" class="r8-close">Close</a></span></div>' + rows +
      '<div class="r8-foot">Need to change something else (e.g. a quantity)? Describe it in <b>Workshop notes</b>. Changes save in this browser automatically. Use <b>Export changes</b> (bottom left) to send them back.</div></div>';
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

    function onEdit(e) {
      var el = e.target, key = el.getAttribute && el.getAttribute('data-key');
      if (!key) return;
      var f = FIELD_BY_KEY[key];
      setEdit(a.id, key, fromInput(f, el.value));
      var row = el.closest('.r8-row'), ch = !same(currentVal(a.id, key), base[a.id][key]);
      row.classList.toggle('r8-changed', ch);
      row.querySelector('.r8-orig').hidden = !ch;
      var n = Object.keys(overlay.edits[a.id] || {}).length, b = document.getElementById('r8-asset-badge');
      b.hidden = !n; b.textContent = n + ' edited';
      dirtyIdx = idx;
      if (el.tagName === 'SELECT') refresh(idx, el.id);   // pathway badge / notes change straight away
    }
    card.addEventListener('input', onEdit);
    card.addEventListener('change', onEdit);
    card.addEventListener('focusout', function (e) {
      if (dirtyIdx === idx && !(e.relatedTarget && card.contains(e.relatedTarget))) setTimeout(function () { if (dirtyIdx === idx) refresh(idx); }, 0);
    });
    card.addEventListener('click', function (e) {
      var k = e.target.getAttribute && e.target.getAttribute('data-revert');
      if (!k) return;
      e.preventDefault();
      setEdit(a.id, k, clone(base[a.id][k]));
      dirtyIdx = null;
      refresh(idx);
    });
  }

  /* Re-render the detail panel + register (keeps scroll and focus) */
  function refresh(idx, focusId, toCard) {
    dirtyIdx = null;
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

  function resetAll() {
    if (!counts().fields) return;
    if (!confirm('Discard ALL your edits in this browser and go back to the original data?\n\nExport first if you want to keep them.')) return;
    overlay = { edits: {} }; meta = { lastExportSig: null, lastExportAt: null };
    saveStore(); location.reload();
  }

  /* ══ Floating bar ══ */
  var barEl = null, toastEl = null, toastT = null;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.hidden = false;
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
  function buildBar() {
    var css = document.createElement('style');
    css.textContent =
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
      '.r8-hint{font-size:11.5px;color:var(--grey-500,#737373);margin-top:2px}' +
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

    barEl = document.createElement('div');
    barEl.id = 'r8-bar';
    barEl.innerHTML = '<span class="r8-tag">REVIEW MODE</span><span class="r8-count"></span><span class="r8-state"></span>' +
      '<button data-act="export">Export changes</button><button data-act="reset">Reset</button>';
    document.body.appendChild(barEl);
    toastEl = document.createElement('div'); toastEl.id = 'r8-toast'; toastEl.hidden = true; document.body.appendChild(toastEl);

    barEl.addEventListener('click', function (e) {
      var act = e.target.getAttribute && e.target.getAttribute('data-act');
      if (act === 'export') exportChanges();
      else if (act === 'reset') resetAll();
    });
    /* The Import button was removed from the toolbar to keep it simple for first-time reviewers.
       importChanges() is kept so it can be wired back to a button (and a hidden <input type=file id=r8-file>) if requested. */
    window.addEventListener('beforeunload', function (e) {
      if (unexported()) { e.preventDefault(); e.returnValue = ''; }
    });
    updateBar();
  }

  window.R8Review = { applyToRaw: applyToRaw, decorate: decorate, afterRender: afterRender, onStarChange: updateBar, _buildExport: buildExport, _fields: FIELDS };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', buildBar); else buildBar();
})();
