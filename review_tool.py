"""
Review submissions: the owner-side screen for reviewer change files.

Registered into edit_assets.py (open http://localhost:5001/review).
A reviewer's export (review_<date>.json, made by the portal's review mode) is a list of
changes: asset id, field, old value (what they were given), new value (what they typed).
This screen walks through them one at a time (accept / reject / skip), then writes only the
accepted ones into data/assets.json, after saving a backup and a decision log.

Nothing is written until you press "Apply" at the end.
"""
import datetime, hashlib, json, re, shutil
from pathlib import Path
from flask import jsonify, request

# Fields a reviewer is allowed to change (anything else in a file is ignored and flagged)
FIELDS = {
    "pathway.suggested":             "Pathway",
    "pathway.partners":              "Primary partner(s)",
    "pathway.partnersSupplementary": "Supplementary partner(s)",
    "notes.workshop":                "Workshop notes",
    "manufacturer":                  "Manufacturer",
    "supplier":                      "Supplier",
}
LIST_FIELDS = {"pathway.partners", "pathway.partnersSupplementary"}
PATHWAYS = {"Retain", "Reuse", "Adaptive Reuse", "Refurbish", "Remanufacture",
            "Rehome", "Stewardship", "Recycle", "Dispose"}
FORMAT = "opgg-review-changes"


def get_path(obj, path):
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def set_path(obj, path, val):
    parts = path.split(".")
    for p in parts[:-1]:
        if not isinstance(obj.get(p), dict):
            obj[p] = {}
        obj = obj[p]
    obj[parts[-1]] = val


def valid_value(field, val):
    """Return an error string, or None if val is acceptable for field."""
    if field in LIST_FIELDS:
        if not isinstance(val, list) or not all(isinstance(x, str) and x.strip() for x in val):
            return "expected a list of names"
    elif val is not None and not isinstance(val, str):
        return "expected text"
    if field == "pathway.suggested" and val is not None and val not in PATHWAYS:
        return f"'{val}' is not a known pathway"
    return None


def norm(v):
    """Blank text and empty list are both 'nothing' so they compare equal."""
    if v is None or v == "" or v == []:
        return None
    return v


def same(a, b):
    return json.dumps(norm(a), sort_keys=True) == json.dumps(norm(b), sort_keys=True)


def register(app, load, save, data_path: Path):
    base = Path(data_path).parent.parent
    review_dir = base / "review"

    def file_hash():
        return hashlib.sha256(Path(data_path).read_bytes()).hexdigest()[:16]

    def read_doc(path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("changes"), list):
            raise ValueError("not a review changes file")
        return doc

    @app.route("/api/review/scan")
    def review_scan():
        folder = Path((request.args.get("dir") or "").strip().strip('"'))
        if not folder.is_dir():
            return jsonify({"error": f"Folder not found: {folder}"}), 400
        out = []
        for p in sorted(folder.rglob("*.json")):
            try:
                d = read_doc(p)
            except Exception:
                continue
            out.append({"path": str(p), "name": str(p.relative_to(folder)), "exportedAt": d.get("exportedAt"),
                        "baseVersion": d.get("baseVersion"), "count": len(d["changes"]),
                        "stars": len(d.get("starred") or []),
                        "mtime": p.stat().st_mtime})
        out.sort(key=lambda x: x.get("exportedAt") or "", reverse=True)
        return jsonify(out)

    @app.route("/api/review/analyse", methods=["POST"])
    def review_analyse():
        body = request.get_json(force=True)
        docs, errors = [], []
        for p in body.get("paths") or []:
            try:
                docs.append((Path(p).name, read_doc(p)))
            except Exception as e:
                errors.append(f"{Path(p).name}: {e}")
        for d in body.get("docs") or []:
            try:
                j = d.get("json")
                if not isinstance(j, dict) or j.get("format") != FORMAT or not isinstance(j.get("changes"), list):
                    raise ValueError("not a review changes file")
                docs.append((d.get("name") or "uploaded file", j))
            except Exception as e:
                errors.append(f"{d.get('name')}: {e}")
        if not docs:
            return jsonify({"error": "No valid review files. " + "; ".join(errors)}), 400

        assets = {a["id"]: a for a in load()}
        notes = []
        cur_hash = file_hash()
        for name, d in docs:
            if d.get("assetsHash") and d["assetsHash"] != cur_hash:
                notes.append(f"{name}: your assets.json has changed since this package was built "
                             f"(version {d.get('baseVersion')}). Cards flagged 'changed since' show where it matters.")

        groups = {}   # (id, field, json(new)) -> item
        for name, d in docs:
            for c in d["changes"]:
                aid, field = c.get("id"), c.get("field")
                a = assets.get(aid)
                new, old = c.get("new"), c.get("old")
                item = {"id": aid, "field": field, "label": FIELDS.get(field, field), "old": old, "new": new,
                        "title": (a or {}).get("title") or c.get("title") or "(unknown asset)",
                        "sources": [name], "image": None, "current": None, "status": "clean", "message": None}
                if field not in FIELDS:
                    item.update(status="invalid", message="This field is not editable by reviewers, so it is ignored.")
                elif a is None:
                    item.update(status="invalid", message="This asset no longer exists in your data.")
                else:
                    err = valid_value(field, new)
                    cur = get_path(a, field)
                    item["current"] = cur
                    imgs = a.get("images") or ([a["imageUrl"]] if a.get("imageUrl") else [])
                    item["image"] = imgs[0] if imgs else None
                    if err:
                        item.update(status="invalid", message=err)
                    elif same(cur, new):
                        item.update(status="applied", message="Already the same in your data.")
                    elif not same(cur, old):
                        item.update(status="changed", message="You have changed this field since the package was shared.")
                key = (aid, field, json.dumps(new, sort_keys=True))
                if key in groups:
                    if name not in groups[key]["sources"]:
                        groups[key]["sources"].append(name)
                else:
                    groups[key] = item
        # assets the reviewer(s) starred, with the figures needed to double-check quantities
        stars = {}
        for name, d in docs:
            for s in (d.get("starred") or []):
                a = assets.get(s.get("id")) if isinstance(s, dict) else None
                if a is None:
                    continue
                st = stars.setdefault(a["id"], {
                    "id": a["id"], "title": a["title"], "category": a.get("category"),
                    "quantity": a.get("quantity"), "unit": a.get("unit"),
                    "weight": (a.get("weight") or {}).get("total"),
                    "pathway": (a.get("pathway") or {}).get("suggested"),
                    "image": ((a.get("images") or [a.get("imageUrl")]) or [None])[0], "sources": []})
                if name not in st["sources"]:
                    st["sources"].append(name)
        starred = sorted(stars.values(), key=lambda x: x["title"].lower())
        items = list(groups.values())
        # competing edits: same asset+field, different new value
        by_af = {}
        for it in items:
            if it["status"] in ("clean", "changed"):
                by_af.setdefault((it["id"], it["field"]), []).append(it)
        for lst in by_af.values():
            if len(lst) > 1:
                for it in lst:
                    it["competing"] = True
                    if it["status"] == "clean":
                        it["status"] = "changed"
                    it["message"] = (it["message"] + " " if it["message"] else "") + \
                        "Another file proposes a different value for this same field. Accepting one rejects the others."
        items.sort(key=lambda x: (x["title"].lower(), list(FIELDS).index(x["field"]) if x["field"] in FIELDS else 99))
        for n, it in enumerate(items):
            it["key"] = f"{it['id']}|{it['field']}|{json.dumps(it['new'], sort_keys=True)}"
            it["n"] = n
        return jsonify({"items": items, "notes": notes, "errors": errors, "starred": starred,
                        "files": [{"name": n, "exportedAt": d.get("exportedAt"), "count": len(d["changes"])} for n, d in docs]})

    @app.route("/api/review/apply", methods=["POST"])
    def review_apply():
        body = request.get_json(force=True)
        accepted = body.get("accepted") or []
        seen = set()
        for c in accepted:
            k = (c.get("id"), c.get("field"))
            if k in seen:
                return jsonify({"error": f"Two accepted changes for the same field ({c.get('field')}). Nothing was written."}), 400
            seen.add(k)
            if c.get("field") not in FIELDS:
                return jsonify({"error": f"Field not allowed: {c.get('field')}. Nothing was written."}), 400
            err = valid_value(c["field"], c.get("new"))
            if err:
                return jsonify({"error": f"{c['field']}: {err}. Nothing was written."}), 400
        assets = load()
        by_id = {a["id"]: a for a in assets}
        missing = [c for c in accepted if c.get("id") not in by_id]
        if missing:
            return jsonify({"error": f"{len(missing)} accepted change(s) refer to assets that no longer exist. Nothing was written."}), 400

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        (review_dir / "backups").mkdir(parents=True, exist_ok=True)
        (review_dir / "logs").mkdir(parents=True, exist_ok=True)
        backup = review_dir / "backups" / f"assets_before_review_{ts}.json"
        shutil.copy2(data_path, backup)

        for c in accepted:
            val = c.get("new")
            if c["field"] in LIST_FIELDS:
                val = list(val or [])
            elif isinstance(val, str) and val.strip() == "":
                val = None
            set_path(by_id[c["id"]], c["field"], val)
        if accepted:
            save(assets)

        log = {"appliedAt": datetime.datetime.now().isoformat(timespec="seconds"),
               "sources": body.get("sources") or [], "backup": str(backup),
               "accepted": accepted, "rejected": body.get("rejected") or [],
               "starredByReviewers": body.get("starred") or [],
               "skipped": body.get("skipped") or []}
        logp = review_dir / "logs" / f"review_{ts}.json"
        logp.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "applied": len(accepted), "rejected": len(log["rejected"]),
                        "skipped": len(log["skipped"]), "backup": str(backup), "log": str(logp)})

    @app.route("/review")
    def review_page():
        return REVIEW_HTML


REVIEW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Review submissions · OPGG BRI</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f5f7;color:#1a1a2e;min-height:100vh}
  header{background:#fff;border-bottom:1px solid #e0e0e8;padding:14px 24px;display:flex;align-items:center;gap:16px}
  header h1{font-size:16px}header a{font-size:13px;color:#e85d26;text-decoration:none;margin-left:auto}
  main{max-width:880px;margin:0 auto;padding:24px}
  .panel{background:#fff;border:1px solid #e0e0e8;border-radius:10px;padding:20px;margin-bottom:16px}
  h2{font-size:14px;margin-bottom:10px}
  p.s{font-size:13px;color:#666;margin-bottom:10px;line-height:1.45}
  input[type=text]{padding:8px 10px;border:1px solid #d0d0dc;border-radius:6px;font-size:13px;width:100%}
  button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;background:#e85d26;color:#fff}
  button.sec{background:#fff;color:#444;border:1px solid #d0d0dc}button:disabled{opacity:.4;cursor:default}
  .row{display:flex;gap:8px;align-items:center}.msg{font-size:13px;margin-top:8px}.err{color:#c62828}.ok{color:#16a34a}
  table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:6px 8px;border-bottom:1px solid #eee;text-align:left}
  /* deck */
  #deck{display:none}.prog{height:6px;background:#e5e5ee;border-radius:3px;overflow:hidden;margin:6px 0 14px}
  .prog>div{height:100%;background:#e85d26;transition:width .2s}
  .card{background:#fff;border:1px solid #e0e0e8;border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.05)}
  .card-top{display:flex;gap:16px;padding:18px;border-bottom:1px solid #eee;align-items:center}
  .card-top img{width:120px;height:120px;object-fit:cover;border-radius:8px;background:#eee;flex-shrink:0}
  .card-top .noimg{width:120px;height:120px;border-radius:8px;background:#eee;flex-shrink:0}
  .card-top h3{font-size:18px}.fld{display:inline-block;margin-top:6px;background:#fff4ef;color:#e85d26;border-radius:5px;padding:3px 9px;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}
  .src{font-size:12px;color:#888;margin-top:6px}
  .warn{background:#fff8e1;border-left:4px solid #f5a623;padding:10px 14px;font-size:13px;line-height:1.4}
  .cmp{padding:16px 18px;display:grid;grid-template-columns:1fr;gap:10px}
  .box{border:1px solid #e0e0e8;border-radius:8px;padding:10px 12px}.box small{display:block;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#888;margin-bottom:4px}
  .box.new{border-color:#16a34a;background:#f3fbf6}.box.cur{border-color:#f5a623;background:#fffaf0}
  .val{font-size:15px;white-space:pre-wrap;word-break:break-word;line-height:1.45}.blank{font-style:italic;color:#999}
  .chip{display:inline-block;border-radius:5px;padding:2px 8px;margin:2px 4px 2px 0;font-size:14px;background:#eef;}
  .chip.add{background:#d6f5df;color:#0b5d2a}.chip.del{background:#fbdada;color:#9b1c1c;text-decoration:line-through}
  .acts{display:flex;gap:10px;justify-content:center;padding:6px 18px 18px}
  .acts button{padding:12px 22px;font-size:15px;min-width:130px}
  .b-rej{background:#fff;color:#c62828;border:2px solid #c62828}.b-acc{background:#16a34a}.b-skip{background:#fff;color:#555;border:2px solid #bbb}
  .keys{text-align:center;font-size:12px;color:#888;padding-bottom:12px}
  .stat{display:flex;gap:18px;font-size:14px;margin:8px 0 14px}.stat b{font-size:20px;display:block}
  .star-row{display:flex;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid #f0f0f5;font-size:13px}
  .star-row img,.star-row .noimg{width:44px;height:44px;border-radius:6px;object-fit:cover;background:#eee;flex-shrink:0}
  .star-row .nm{font-weight:600}.star-row .mt{color:#666;font-size:12px}.star-row .q{margin-left:auto;text-align:right;white-space:nowrap}
  .tag{font-size:11px;border-radius:4px;padding:1px 6px;font-weight:700}.t-a{background:#d6f5df;color:#0b5d2a}.t-r{background:#fbdada;color:#9b1c1c}.t-s{background:#eee;color:#555}
</style>
</head>
<body>
<header><h1>Review submissions</h1><a href="/">← Back to the asset editor</a></header>
<main>

<div class="panel" id="load">
  <h2>1 · Choose the reviewer file(s)</h2>
  <p class="s">Point to the shared Submissions folder and tick the file(s) to review, or pick files from your computer.
     Each reviewer export lists <i>everything</i> that person changed, so for one reviewer use their newest file only.</p>
  <div class="row"><input type="text" id="dir" placeholder="Submissions folder, e.g. C:\Users\you\SharePoint\OPGG\Submissions">
    <button class="sec" onclick="scan()">Scan folder</button></div>
  <div id="files" style="margin-top:10px"></div>
  <div class="row" style="margin-top:10px">
    <input type="file" id="pick" accept=".json" multiple style="font-size:13px">
    <button id="go" onclick="analyse()">Start review</button>
  </div>
  <div class="msg" id="loadmsg"></div>
</div>

<div class="panel" id="stars" style="display:none"></div>

<div id="deck">
  <div class="panel" style="padding:14px 20px">
    <div class="row"><b id="pos"></b><span style="flex:1"></span>
      <button class="sec" onclick="finish()">Finish &amp; apply ›</button></div>
    <div class="prog"><div id="bar" style="width:0"></div></div>
    <div id="notes"></div>
  </div>
  <div class="card" id="card"></div>
  <div class="keys">Keyboard: <b>→</b> accept · <b>←</b> reject · <b>↓</b> skip for now · <b>↑</b> / Backspace undo</div>
</div>

<div class="panel" id="summary" style="display:none"></div>
</main>

<script>
let items = [], idx = 0, dec = {}, files = [], sources = [], starList = [];
const $ = id => document.getElementById(id);
const esc = s => String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
try { $('dir').value = localStorage.getItem('r8-sub-dir') || ''; } catch(e) {}

async function scan() {
  const d = $('dir').value.trim(); if (!d) return;
  try { localStorage.setItem('r8-sub-dir', d); } catch(e) {}
  const r = await fetch('/api/review/scan?dir=' + encodeURIComponent(d)), j = await r.json();
  if (!r.ok) { $('files').innerHTML = '<div class="msg err">' + esc(j.error) + '</div>'; return; }
  files = j;
  $('files').innerHTML = j.length ? '<table><tr><th></th><th>File</th><th>Exported</th><th>Changes</th><th>Starred</th></tr>' + j.map((f,i) =>
    '<tr><td><input type="checkbox" class="fc" data-i="' + i + '"></td><td>' + esc(f.name) + '</td><td>' +
    esc((f.exportedAt||'').replace('T',' ').slice(0,16)) + '</td><td>' + f.count + '</td><td>' + (f.stars||0) + '</td></tr>').join('') + '</table>'
    : '<div class="msg">No review files found in that folder.</div>';
}

function readFile(f) { return new Promise((res, rej) => { const r = new FileReader();
  r.onload = () => { try { res({name: f.name, json: JSON.parse(r.result)}); } catch(e) { rej(f.name + ': not valid JSON'); } };
  r.readAsText(f); }); }

async function analyse() {
  $('loadmsg').textContent = ''; $('loadmsg').className = 'msg';
  const paths = [...document.querySelectorAll('.fc:checked')].map(c => files[+c.dataset.i].path);
  let docs = [];
  try { docs = await Promise.all([...($('pick').files||[])].map(readFile)); } catch(e) { $('loadmsg').textContent = e; $('loadmsg').className = 'msg err'; return; }
  if (!paths.length && !docs.length) { $('loadmsg').textContent = 'Tick a file from the folder list, or choose a file.'; $('loadmsg').className = 'msg err'; return; }
  const r = await fetch('/api/review/analyse', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({paths, docs})});
  const j = await r.json();
  if (!r.ok) { $('loadmsg').textContent = j.error; $('loadmsg').className = 'msg err'; return; }
  sources = j.files.map(f => f.name);
  items = j.items; starList = j.starred || [];
  renderStars();
  let saved = {}; try { saved = JSON.parse(localStorage.getItem('r8-sub-dec') || '{}'); } catch(e) {}
  dec = {}; items.forEach(it => { if (saved[it.key]) dec[it.key] = saved[it.key]; });
  // items already identical in your data are not asked about
  items.forEach(it => { if (it.status === 'applied' || it.status === 'invalid') dec[it.key] = 'skip-auto'; });
  $('notes').innerHTML = j.notes.concat(j.errors).map(n => '<div class="warn" style="margin-top:6px">' + esc(n) + '</div>').join('');
  history = []; idx = items.findIndex(it => !dec[it.key]);
  $('load').style.display = 'none'; $('summary').style.display = 'none'; $('deck').style.display = 'block';
  if (idx < 0) { idx = 0; finish(); return; }
  render();
}

const EDITOR_STAR_KEY = 'r8-editor-starred-assets';   // same browser address as the editor, so we can add to its stars
function renderStars() {
  const el = $('stars');
  if (!starList.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
  const row = s => '<div class="star-row">' + (s.image ? '<img src="/' + encodeURI(s.image) + '" alt="">' : '<div class="noimg"></div>') +
    '<div><div class="nm">\u2605 ' + esc(s.title) + '</div><div class="mt">' + esc(s.category || '') + (s.pathway ? ' \u00b7 ' + esc(s.pathway) : '') +
    ' \u00b7 from ' + s.sources.map(esc).join(', ') + '</div></div>' +
    '<div class="q"><b>' + (s.quantity == null ? '\u2014' : Number(s.quantity).toLocaleString()) + '</b> ' + esc(s.unit || '') +
    (s.weight ? '<div class="mt">' + Math.round(s.weight).toLocaleString() + ' kg</div>' : '') + '</div></div>';
  el.style.display = 'block';
  el.innerHTML = '<h2>\u2605 Starred by reviewer(s) \u2014 ' + starList.length + ' asset' + (starList.length === 1 ? '' : 's') + '</h2>' +
    '<p class="s">Assets the reviewer(s) flagged for a quantity double-check. Quantities shown are the ones currently in your data.</p>' +
    '<div class="row" style="margin-bottom:6px"><button class="sec" onclick="addStarsToEditor()">Add these to my starred assets</button>' +
    '<span class="msg" id="starmsg" style="margin:0"></span></div>' + starList.map(row).join('');
}
function addStarsToEditor() {
  let cur = []; try { cur = JSON.parse(localStorage.getItem(EDITOR_STAR_KEY)) || []; } catch(e) {}
  const set = new Set(cur); let added = 0;
  starList.forEach(s => { if (!set.has(s.id)) { set.add(s.id); added++; } });
  try { localStorage.setItem(EDITOR_STAR_KEY, JSON.stringify([...set])); $('starmsg').className = 'msg ok'; $('starmsg').textContent = added + ' added to your starred assets in the editor.'; }
  catch(e) { $('starmsg').className = 'msg err'; $('starmsg').textContent = 'Could not save to this browser.'; }
}

function chips(cur, other, cls) {
  const o = new Set((other||[]).map(x => x.toLowerCase()));
  return (cur||[]).map(x => '<span class="chip ' + (o.has(x.toLowerCase()) ? '' : cls) + '">' + esc(x) + '</span>').join('') || '<span class="blank">(none)</span>';
}
function show(it, v) {
  if (Array.isArray(v)) return '<div class="val">' + (v.length ? v.map(x => '<span class="chip">' + esc(x) + '</span>').join('') : '<span class="blank">(none)</span>') + '</div>';
  return '<div class="val">' + (v == null || v === '' ? '<span class="blank">(blank)</span>' : esc(v)) + '</div>';
}
function list(it) { return it.field.indexOf('partners') >= 0 || it.field === 'pathway.partnersSupplementary'; }

function render() {
  const todo = items.filter(it => dec[it.key] !== 'skip-auto');
  const done = todo.filter(it => dec[it.key] && dec[it.key] !== 'skip').length;
  $('pos').textContent = todo.length ? 'Reviewed ' + done + ' of ' + todo.length : 'Nothing to review';
  $('bar').style.width = (todo.length ? done / todo.length * 100 : 100) + '%';
  const it = items[idx];
  if (!it || !todo.length) { finish(); return; }
  const d = dec[it.key];
  const l = list(it);
  const newHtml = l ? '<div class="val">' + chips(it.new, it.current, 'add') + (it.current && it.current.length ? '' : '') +
        ((it.current||[]).filter(x => !(it.new||[]).map(y=>y.toLowerCase()).includes(x.toLowerCase())).map(x => '<span class="chip del">' + esc(x) + '</span>').join('')) + '</div>'
      : show(it, it.new);
  $('card').innerHTML =
    '<div class="card-top">' + (it.image ? '<img src="/' + encodeURI(it.image) + '" alt="">' : '<div class="noimg"></div>') +
    '<div><h3>' + esc(it.title) + '</h3><span class="fld">' + esc(it.label) + '</span>' +
    '<div class="src">From: ' + it.sources.map(esc).join(', ') + '</div>' +
    (d ? '<div style="margin-top:6px"><span class="tag ' + (d==='accept'?'t-a':d==='reject'?'t-r':'t-s') + '">' + (d==='accept'?'ACCEPTED':d==='reject'?'REJECTED':'SKIPPED') + '</span></div>' : '') +
    '</div></div>' +
    (it.message ? '<div class="warn">' + esc(it.message) + '</div>' : '') +
    '<div class="cmp">' +
      (it.status === 'changed' ? '<div class="box cur"><small>Your data now</small>' + show(it, it.current) + '</div>' : '') +
      '<div class="box"><small>' + (it.status === 'changed' ? 'Reviewer started from' : 'Currently') + '</small>' + show(it, it.old) + '</div>' +
      '<div class="box new"><small>Reviewer\u2019s change' + (l ? ' (green = added, red = removed)' : '') + '</small>' + newHtml + '</div>' +
    '</div>' +
    '<div class="acts"><button class="b-rej" onclick="decide(\'reject\')">✗ Reject</button>' +
    '<button class="b-skip" onclick="decide(\'skip\')">Skip</button>' +
    '<button class="b-acc" onclick="decide(\'accept\')">✓ Accept</button></div>';
}

function persist() { try { localStorage.setItem('r8-sub-dec', JSON.stringify(dec)); } catch(e) {} }
function nextIdx(from) {
  for (let i = from + 1; i < items.length; i++) if (!dec[items[i].key]) return i;
  for (let i = 0; i <= from; i++) if (!dec[items[i].key]) return i;
  return -1;
}
let history = [];
function decide(v) {
  const it = items[idx]; if (!it) return;
  history.push({idx, prev: dec[it.key], others: {}});
  dec[it.key] = v;
  if (v === 'accept' && it.competing) items.forEach(o => { if (o !== it && o.id === it.id && o.field === it.field && dec[o.key] !== 'skip-auto') { history[history.length-1].others[o.key] = dec[o.key]; dec[o.key] = 'reject'; } });
  persist();
  const n = nextIdx(idx);
  if (n < 0) { finish(); return; }
  idx = n; render();
}
function undo() {
  const h = history.pop(); if (!h) return;
  const it = items[h.idx]; if (h.prev) dec[it.key] = h.prev; else delete dec[it.key];
  Object.keys(h.others).forEach(k => { if (h.others[k]) dec[k] = h.others[k]; else delete dec[k]; });
  persist(); idx = h.idx; $('summary').style.display = 'none'; $('deck').style.display = 'block'; render();
}
document.addEventListener('keydown', e => {
  if ($('deck').style.display !== 'block' || e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowRight') { e.preventDefault(); decide('accept'); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); decide('reject'); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); decide('skip'); }
  else if (e.key === 'ArrowUp' || e.key === 'Backspace') { e.preventDefault(); undo(); }
});

function finish() {
  const acc = items.filter(i => dec[i.key] === 'accept'), rej = items.filter(i => dec[i.key] === 'reject'),
        skp = items.filter(i => !dec[i.key] || dec[i.key] === 'skip'), auto = items.filter(i => dec[i.key] === 'skip-auto');
  const row = (i, t, c) => '<tr><td><span class="tag ' + c + '">' + t + '</span></td><td>' + esc(i.title) + '</td><td>' + esc(i.label) + '</td></tr>';
  $('deck').style.display = 'none'; $('summary').style.display = 'block';
  $('summary').innerHTML = '<h2>Summary</h2><div class="stat"><div><b>' + acc.length + '</b>accepted</div><div><b>' + rej.length +
    '</b>rejected</div><div><b>' + skp.length + '</b>skipped</div>' + (auto.length ? '<div><b>' + auto.length + '</b>already applied / ignored</div>' : '') + '</div>' +
    '<p class="s">Only accepted changes are written to assets.json, after a backup is saved. Rejected and skipped items are recorded in the log and left as they are.</p>' +
    '<div class="row"><button class="sec" onclick="undoBack()">‹ Back to review</button>' +
    '<button id="apply" onclick="apply()"' + (acc.length ? '' : ' disabled') + '>Apply ' + acc.length + ' accepted change' + (acc.length === 1 ? '' : 's') + '</button></div>' +
    '<div class="msg" id="applymsg"></div><table style="margin-top:14px">' +
    acc.map(i => row(i, 'ACCEPT', 't-a')).join('') + rej.map(i => row(i, 'REJECT', 't-r')).join('') + skp.map(i => row(i, 'SKIP', 't-s')).join('') + '</table>';
}
function undoBack() { $('summary').style.display = 'none'; $('deck').style.display = 'block'; const n = items.findIndex(i => !dec[i.key] || dec[i.key] === 'skip'); if (n >= 0) idx = n; render(); }

async function apply() {
  const pick = f => items.filter(f).map(i => ({id: i.id, title: i.title, field: i.field, old: i.old, 'new': i.new, current: i.current}));
  $('apply').disabled = true;
  const r = await fetch('/api/review/apply', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
    accepted: pick(i => dec[i.key] === 'accept'), rejected: pick(i => dec[i.key] === 'reject'),
    skipped: pick(i => !dec[i.key] || dec[i.key] === 'skip'), sources,
    starred: starList.map(s => ({id: s.id, title: s.title, quantity: s.quantity, unit: s.unit}))})});
  const j = await r.json(), m = $('applymsg');
  if (!r.ok) { m.className = 'msg err'; m.textContent = j.error; $('apply').disabled = false; return; }
  m.className = 'msg ok';
  m.innerHTML = 'Applied ' + j.applied + ' change(s) to assets.json.<br>Backup: ' + esc(j.backup) + '<br>Log: ' + esc(j.log);
  try { localStorage.removeItem('r8-sub-dec'); } catch(e) {}
}
</script>
</body>
</html>
"""
