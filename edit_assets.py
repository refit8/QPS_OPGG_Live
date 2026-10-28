"""
OPGG BRI Pilot — Local Asset Editor
Standalone Flask app for editing data/assets.json without touching the file directly.
Run with: python edit_assets.py
Opens a browser UI at http://localhost:5001 — search, view, edit, and save assets.
Writes changes directly back to data/assets.json on save.
"""

import json, os, sys, webbrowser, threading, copy, uuid, re
from pathlib import Path
try:
    import flask, PIL, pillow_heif
except ImportError:
    print("Installing dependencies (flask, pillow, pillow-heif)…")
    os.system(f"{sys.executable} -m pip install flask pillow pillow-heif -q")

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from flask import Flask, jsonify, request, send_from_directory

# ── Paths ────────────────────────────────────────────────────────────────────
BASE   = Path(__file__).parent
DATA   = BASE / "data" / "assets.json"
IMAGES = BASE / "data" / "images" / "images_assets"

app = Flask(__name__, static_folder=str(BASE))

register_heif_opener()  # lets Pillow read iPhone HEIC/HEIF files
HEIC_EXTS = {".heic", ".heif"}

# ── Data helpers ─────────────────────────────────────────────────────────────
def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)

def save(data):
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ── API ───────────────────────────────────────────────────────────────────────
@app.route("/api/assets")
def api_list():
    q = request.args.get("q", "").lower()
    assets = load()
    if q:
        assets = [a for a in assets if
            q in (a.get("title") or "").lower() or
            q in (a.get("primaryMaterialStream") or "").lower() or
            q in (a.get("category") or "").lower() or
            q in ((a.get("pathway") or {}).get("suggested") or "").lower()
        ]
    # Return lightweight list
    return jsonify([{
        "id": a["id"],
        "title": a["title"],
        "category": a.get("category"),
        "primaryMaterialStream": a.get("primaryMaterialStream"),
        "pathway": (a.get("pathway") or {}).get("suggested"),
        "quantity": a.get("quantity"),
        "imageUrl": a.get("imageUrl"),
    } for a in assets])

@app.route("/api/materials")
def api_materials():
    """Distinct primaryMaterialStream values in use — same list the portal's Material filter shows."""
    return jsonify(sorted({a["primaryMaterialStream"] for a in load() if a.get("primaryMaterialStream")}))

@app.route("/api/assets/<aid>")
def api_get(aid):
    assets = load()
    item = next((a for a in assets if a["id"] == aid), None)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)

@app.route("/api/assets/<aid>", methods=["PUT"])
def api_update(aid):
    assets = load()
    idx = next((i for i, a in enumerate(assets) if a["id"] == aid), None)
    if idx is None:
        return jsonify({"error": "Not found"}), 404
    patch = request.json
    merged = deep_merge(assets[idx], patch)
    assets[idx] = merged
    save(assets)
    return jsonify({"ok": True, "asset": merged})

@app.route("/api/assets/<aid>", methods=["DELETE"])
def api_delete(aid):
    assets = load()
    idx = next((i for i, a in enumerate(assets) if a["id"] == aid), None)
    if idx is None:
        return jsonify({"error": "Not found"}), 404
    # Write backup before deleting
    backup_path = DATA.parent / "assets - pre-delete-backup.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(assets, f, indent=2, ensure_ascii=False)
    removed = assets.pop(idx)
    save(assets)
    return jsonify({"ok": True, "removed": removed["title"]})

@app.route("/api/assets", methods=["POST"])
def api_add():
    assets = load()
    new_id = str(uuid.uuid4())
    blank = blank_asset(new_id)
    assets.append(blank)
    save(assets)
    return jsonify({"ok": True, "asset": blank}), 201

# Serve images for preview
@app.route("/data/images/images_assets/<path:name>")
def asset_image(name):
    resp = send_from_directory(str(IMAGES), name)
    resp.headers["Cache-Control"] = "no-store"  # never show a stale image for a reused filename
    return resp

@app.route("/api/assets/<aid>/images", methods=["POST"])
def api_add_images(aid):
    assets = load()
    idx = next((i for i, a in enumerate(assets) if a["id"] == aid), None)
    if idx is None:
        return jsonify({"error": "Not found"}), 404
    asset = assets[idx]
    files = request.files.getlist("photo")
    if not files:
        return jsonify({"error": "No file uploaded"}), 400

    stem = safe_stem(asset.get("title"))
    images = list(asset.get("images") or [])
    # Guard against images[] having been reset/desynced from imageUrl (has happened
    # before via an external overwrite) — never let a new upload look like it
    # replaced the existing cover photo.
    cover = asset.get("imageUrl")
    if cover and cover not in images:
        images.insert(0, cover)
    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
        if not images and not (IMAGES / f"{stem}{ext}").exists():
            filename = f"{stem}{ext}"
        else:
            n = len(images) + 1
            filename = f"{stem} - {n}{ext}"
            while (IMAGES / filename).exists():
                n += 1
                filename = f"{stem} - {n}{ext}"
        if ext in HEIC_EXTS:
            # Browsers can't display HEIC — convert to JPEG, honouring phone rotation
            filename = os.path.splitext(filename)[0] + ".jpg"
            while (IMAGES / filename).exists():
                n += 1
                filename = f"{stem} - {n}.jpg"
            img = ImageOps.exif_transpose(Image.open(file.stream)).convert("RGB")
            img.save(IMAGES / filename, "JPEG", quality=90)
        else:
            file.save(IMAGES / filename)
        images.append(f"data/images/images_assets/{filename}")

    asset["images"] = images
    if not asset.get("imageUrl") and images:
        asset["imageUrl"] = images[0]
    assets[idx] = asset
    save(assets)
    return jsonify({"ok": True, "asset": asset})

@app.route("/api/assets/<aid>/images", methods=["DELETE"])
def api_remove_image(aid):
    assets = load()
    idx = next((i for i, a in enumerate(assets) if a["id"] == aid), None)
    if idx is None:
        return jsonify({"error": "Not found"}), 404
    asset = assets[idx]
    path = (request.json or {}).get("path")
    images = list(asset.get("images") or [])
    if path in images:
        images.remove(path)
    asset["images"] = images
    if asset.get("imageUrl") == path:
        asset["imageUrl"] = images[0] if images else None
    assets[idx] = asset
    save(assets)
    return jsonify({"ok": True, "asset": asset})

# ── Helpers ───────────────────────────────────────────────────────────────────
def safe_stem(title):
    # strip characters that are invalid in Windows filenames
    return re.sub(r'[<>:"/\\|?*]', '', title or 'asset').strip() or 'asset'

def deep_merge(base, patch):
    result = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def blank_asset(new_id):
    return {
        "id": new_id, "title": "New Asset", "imageUrl": None, "images": [],
        "category": "Built Form", "unit": "Count", "quantity": 1,
        "manufacturer": None, "supplier": None,
        "dimensions": {"height": None, "depth": None, "width": None},
        "primaryMaterialStream": None,
        "weight": {"perUnit": None, "total": None},
        "pathway": {"suggested": None, "suggestedId": None, "partners": [], "partnersSupplementary": []},
        "location": None,
        "notes": {"audit": None, "workshop": None},
        "embodiedCarbon": {"perUnit": None, "ecSource": "estimate", "total": None},
        "wasteEmissions": {"factor": None, "efSource": None, "potential": None},
        "pathwayNotes": {
            "retain": None, "reuse": None, "adaptiveReuse": None,
            "refurbish": None, "recycle": None, "disposal": None,
            "rehome": None, "remanufacture": None, "stewardship": None,
        },
        "pathwayConfirmed": None,
    }

# ── Frontend (inline HTML) ────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>OPGG BRI Asset Editor</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f4f5f7; color: #1a1a2e; display: flex; height: 100vh; overflow: hidden; }

  /* ── Left panel ── */
  #left { width: 320px; min-width: 260px; background: #fff; border-right: 1px solid #e0e0e8;
          display: flex; flex-direction: column; }
  #left header { padding: 18px 16px 12px; border-bottom: 1px solid #e0e0e8; }
  #left header h1 { font-size: 15px; font-weight: 700; color: #1a1a2e; }
  #left header p  { font-size: 11px; color: #888; margin-top: 2px; }
  #search-wrap { padding: 10px 12px; border-bottom: 1px solid #e0e0e8; display: flex; gap: 6px; }
  #search { flex: 1; padding: 7px 10px; border: 1px solid #d0d0dc; border-radius: 6px;
            font-size: 13px; outline: none; }
  #search:focus { border-color: #e85d26; }
  #btn-add { padding: 7px 11px; background: #e85d26; color: #fff; border: none;
             border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
  #btn-add:hover { background: #c94d1c; }
  #sort-wrap { padding: 0 12px 10px; border-bottom: 1px solid #e0e0e8; display: flex;
               align-items: center; gap: 6px; }
  #sort-wrap label { font-size: 11px; color: #888; font-weight: 600; white-space: nowrap; }
  #sort-mode { flex: 1; padding: 6px 8px; border: 1px solid #d0d0dc; border-radius: 6px;
               font-size: 12px; background: #fff; outline: none; }
  #sort-mode:focus { border-color: #e85d26; }
  #asset-list { flex: 1; overflow-y: auto; }
  .star-btn { display: inline-flex; padding: 3px; border: 0; background: none; cursor: pointer; flex-shrink: 0; }
  .star-btn svg { width: 16px; height: 16px; fill: none; stroke: #c4c4d0; stroke-width: 2; stroke-linejoin: round; }
  .star-btn:hover svg { stroke: #e85d26; }
  .star-btn.on svg { fill: #e85d26; stroke: #e85d26; }
  .asset-row:not(:hover) .star-btn:not(.on) { visibility: hidden; }
  #btn-star-first { display: inline-flex; padding: 5px 7px; border: 1px solid #d0d0dc; border-radius: 6px;
                    background: #fff; cursor: pointer; }
  #btn-star-first svg { width: 16px; height: 16px; fill: none; stroke: #e85d26; stroke-width: 2; stroke-linejoin: round; }
  #btn-star-first.on { border-color: #e85d26; background: #fff4ef; }
  #btn-star-first.on svg { fill: #e85d26; }
  .asset-row.star-end { border-bottom: 2px solid #e85d26; }
  #ed-star .star-btn svg { width: 22px; height: 22px; stroke: #e85d26; }
  .asset-row { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
               cursor: pointer; border-bottom: 1px solid #f0f0f5; transition: background .1s; }
  .asset-row:hover { background: #f7f7fb; }
  .asset-row.active { background: #fff4ef; border-left: 3px solid #e85d26; }
  .asset-thumb { width: 38px; height: 38px; border-radius: 5px; object-fit: cover;
                 background: #eee; flex-shrink: 0; }
  .asset-thumb-placeholder { width: 38px; height: 38px; border-radius: 5px; background: #e8e8f0;
                              flex-shrink: 0; display: flex; align-items: center; justify-content: center;
                              font-size: 18px; color: #aaa; }
  .asset-info { min-width: 0; }
  .asset-info strong { font-size: 13px; display: block; white-space: nowrap;
                       overflow: hidden; text-overflow: ellipsis; }
  .asset-info span   { font-size: 11px; color: #888; }
  .pill { display: inline-block; padding: 1px 7px; border-radius: 20px; font-size: 10px;
          font-weight: 600; margin-left: 4px; vertical-align: middle; }

  /* ── Right panel ── */
  #right { flex: 1; overflow-y: auto; padding: 28px 32px; }
  #placeholder { display: flex; align-items: center; justify-content: center;
                 height: 100%; color: #bbb; font-size: 15px; }
  #editor { display: none; }

  .editor-header { display: flex; align-items: flex-start; gap: 20px; margin-bottom: 24px; }
  .editor-img { width: 80px; height: 80px; border-radius: 8px; object-fit: cover;
                background: #eee; flex-shrink: 0; }
  .editor-img-ph { width: 80px; height: 80px; border-radius: 8px; background: #e8e8f0;
                   display: flex; align-items: center; justify-content: center;
                   font-size: 32px; color: #ccc; flex-shrink: 0; }
  .editor-title-row { flex: 1; min-width: 0; }
  .editor-title-row h2 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
  .editor-title-row p  { font-size: 12px; color: #888; }

  .btn-save { padding: 9px 22px; background: #e85d26; color: #fff; border: none;
              border-radius: 7px; font-size: 13px; font-weight: 700; cursor: pointer; }
  .btn-save:hover { background: #c94d1c; }
  .btn-save:disabled { background: #ccc; cursor: default; }
  .btn-delete { padding: 9px 16px; background: #fff; color: #c94040; border: 1.5px solid #c94040;
                border-radius: 7px; font-size: 13px; font-weight: 700; cursor: pointer; }
  .btn-delete:hover { background: #fff0f0; }
  .field input.calc { background: #f0f5ff; color: #444; font-style: italic; }
  .save-status { font-size: 12px; margin-left: 10px; color: #888; }
  .save-ok  { color: #2a9d5c; }
  .save-err { color: #e84242; }

  .section { background: #fff; border-radius: 10px; padding: 20px 22px;
             margin-bottom: 16px; border: 1px solid #e8e8f0; }
  .section h3 { font-size: 12px; font-weight: 700; text-transform: uppercase;
                letter-spacing: .06em; color: #888; margin-bottom: 14px; }
  .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 20px; }
  .field-grid.three { grid-template-columns: 1fr 1fr 1fr; }
  .field-grid.one   { grid-template-columns: 1fr; }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 11px; font-weight: 600; color: #666; }
  .field input, .field select, .field textarea {
    padding: 7px 9px; border: 1px solid #d8d8e8; border-radius: 6px;
    font-size: 13px; font-family: inherit; color: #1a1a2e; background: #fff;
    transition: border-color .15s; resize: vertical; }
  .field input:focus, .field select:focus, .field textarea:focus {
    outline: none; border-color: #e85d26; }
  .field input[readonly] { background: #f5f5f8; color: #999; cursor: not-allowed; }
  .field textarea { min-height: 80px; }
  .field .null-val { font-size: 12px; color: #bbb; font-style: italic; }

  .pathway-notes .field { margin-bottom: 10px; }
  .pathway-notes .field label { display: flex; align-items: center; gap: 6px; }
  .pathway-badge { display: inline-block; padding: 1px 8px; border-radius: 20px;
                   font-size: 10px; font-weight: 700; }

  .photo-gallery { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
  .photo-item { position: relative; width: 84px; height: 84px; border-radius: 8px;
                overflow: hidden; background: #eee; border: 1px solid #e0e0e8; }
  .photo-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .photo-item.cover::after { content: 'Cover'; position: absolute; bottom: 0; left: 0; right: 0;
                              background: rgba(232,93,38,.85); color: #fff; font-size: 9px;
                              text-align: center; padding: 1px 0; }
  .photo-remove { position: absolute; top: 2px; right: 2px; width: 18px; height: 18px;
                   border-radius: 50%; background: rgba(0,0,0,.6); color: #fff; border: none;
                   font-size: 11px; line-height: 18px; cursor: pointer; padding: 0; }
  .photo-move { position: absolute; top: 2px; width: 18px; height: 18px; border-radius: 3px;
                background: rgba(0,0,0,.55); color: #fff; border: none; font-size: 11px;
                cursor: pointer; padding: 0; }
  .photo-move.left  { left: 2px; }
  .photo-move.right { left: 22px; }
  .photo-empty { font-size: 12px; color: #aaa; font-style: italic; }
  .btn-upload { padding: 7px 14px; background: #fff; color: #e85d26; border: 1.5px solid #e85d26;
                border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; }
  .btn-upload:hover { background: #fff4ef; }
  .dropzone { border: 2px dashed #d0d0dc; border-radius: 10px; padding: 14px; transition: all .15s; }
  .dropzone.dragover { border-color: #e85d26; background: #fff4ef; }
  .drop-hint { font-size: 12px; color: #aaa; }
</style>
</head>
<body>

<!-- Left: asset list -->
<div id="left">
  <header>
    <h1>OPGG BRI Asset Editor</h1>
    <p id="count-label">Loading…</p>
  </header>
  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search title, material, pathway…">
    <button id="btn-add" onclick="addAsset()">+ New</button>
  </div>
  <div id="sort-wrap">
    <button id="btn-star-first" onclick="toggleStarFirst()" aria-pressed="false" title="Show starred assets first">
      <svg viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"/></svg>
    </button>
    <label for="sort-mode">Sort</label>
    <select id="sort-mode">
      <option value="">File order</option>
      <option value="title">Title (A–Z)</option>
      <option value="category">Category</option>
      <option value="pathway">Pathway</option>
    </select>
  </div>
  <div id="asset-list"></div>
</div>

<!-- Right: editor -->
<div id="right">
  <div id="placeholder">← Select an asset to edit</div>
  <div id="editor">

    <div class="editor-header">
      <div id="ed-img-wrap"></div>
      <div class="editor-title-row">
        <h2 id="ed-title">—</h2>
        <p id="ed-meta">—</p>
      </div>
      <span id="ed-star"></span>
      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
        <button class="btn-save" id="btn-save" onclick="saveAsset()">Save</button>
        <button class="btn-delete" id="btn-delete" onclick="deleteAsset()">Delete</button>
        <span id="save-status" class="save-status"></span>
      </div>
    </div>

    <!-- Photos -->
    <div class="section">
      <h3>Photos</h3>
      <div id="photo-dropzone" class="dropzone">
      <div id="photo-gallery" class="photo-gallery"></div>
      <div style="display:flex;align-items:center;gap:10px">
        <input type="file" id="f-photo-upload" accept="image/*" multiple style="display:none">
        <button class="btn-upload" onclick="document.getElementById('f-photo-upload').click()">+ Add Photos</button>
        <span class="drop-hint">or drag &amp; drop images here</span>
        <span id="photo-upload-status" class="save-status"></span>
      </div>
      </div>
    </div>

    <!-- Core fields -->
    <div class="section">
      <h3>Core Details</h3>
      <div class="field-grid">
        <div class="field"><label>ID</label><input id="f-id" readonly></div>
        <div class="field"><label>Title</label><input id="f-title"></div>
        <div class="field">
          <label>Category</label>
          <select id="f-category">
            <option>Built Form</option><option>FF&E</option><option>Services</option><option>Construction Waste</option>
          </select>
        </div>
        <div class="field">
          <label>Unit</label>
          <select id="f-unit">
            <option>Count</option><option>Mass (kg)</option><option>Area (m2)</option><option>Linear Metre (m)</option><option>Volume (m3)</option>
          </select>
        </div>
        <div class="field"><label>Quantity</label><input id="f-quantity" type="number" min="0" oninput="recalc()"></div>
        <div class="field"><label>Location</label><input id="f-location" placeholder="null"></div>
        <div class="field"><label>Manufacturer</label><input id="f-manufacturer" placeholder="null"></div>
        <div class="field"><label>Supplier</label><input id="f-supplier" placeholder="null"></div>
        <div class="field"><label>Primary Material Stream</label><select id="f-pms" onchange="onMaterialChange(this)"></select></div>
      </div>
    </div>

    <!-- Pathway -->
    <div class="section">
      <h3>Pathway</h3>
      <div class="field-grid three">
        <div class="field">
          <label>Suggested Pathway</label>
          <select id="f-pathway-suggested">
            <option value="">— none —</option>
            <option>Retain</option><option>Reuse</option><option>Adaptive Reuse</option>
            <option>Refurbish</option><option>Recycle</option><option>Dispose</option>
            <option>Rehome</option><option>Remanufacture</option><option>Stewardship</option>
          </select>
        </div>
        <div class="field"><label>Partners (comma-separated)</label><input id="f-partners" placeholder="e.g. ALD, Milliken"></div>
        <div class="field"><label>Partners Supplementary</label><input id="f-partners-supp" placeholder="e.g. Surface Mine"></div>
      </div>
    </div>

    <!-- Weight & Dimensions -->
    <div class="section">
      <h3>Weight & Dimensions</h3>
      <div class="field-grid three">
        <div class="field"><label>Weight per Unit (kg)</label><input id="f-weight-per" type="number" step="any" oninput="recalc()"></div>
        <div class="field"><label>Total Weight (kg) <em style="font-weight:400;color:#aaa">auto</em></label><input id="f-weight-total" class="calc" readonly></div>
        <div class="field" style="grid-column:span 1"></div>
        <div class="field"><label>Height (mm)</label><input id="f-dim-h" type="number" step="any" placeholder="null"></div>
        <div class="field"><label>Depth (mm)</label><input id="f-dim-d" type="number" step="any" placeholder="null"></div>
        <div class="field"><label>Width (mm)</label><input id="f-dim-w" type="number" step="any" placeholder="null"></div>
      </div>
    </div>

    <!-- Environmental -->
    <div class="section">
      <h3>Environmental Impact</h3>
      <div class="field-grid three">
        <div class="field"><label>EC per Unit (kgCO₂e)</label><input id="f-ec-per" type="number" step="any" oninput="recalc()"></div>
        <div class="field"><label>EC Total (kgCO₂e) <em style="font-weight:400;color:#aaa">auto</em></label><input id="f-ec-total" class="calc" readonly></div>
        <div class="field">
          <label>EC Source</label>
          <input id="f-ec-src" type="text" placeholder="estimate">
        </div>
        <div class="field"><label>WE Factor</label><input id="f-we-factor" type="number" step="any" oninput="recalc()"></div>
        <div class="field"><label>WE Potential (kgCO₂e) <em style="font-weight:400;color:#aaa">auto</em></label><input id="f-we-pot" class="calc" readonly></div>
        <div class="field"><label>EF Source</label><input id="f-we-src"></div>
      </div>
    </div>

    <!-- Notes -->
    <div class="section">
      <h3>Notes</h3>
      <div class="field-grid one">
        <div class="field"><label>Audit Notes</label><textarea id="f-notes-audit"></textarea></div>
        <div class="field"><label>Workshop Notes</label><textarea id="f-notes-workshop"></textarea></div>
      </div>
    </div>

    <!-- Pathway Notes -->
    <div class="section pathway-notes">
      <h3>Pathway Notes</h3>
      <div class="field-grid one" id="pathway-notes-grid">
        <!-- populated by JS -->
      </div>
    </div>

  </div><!-- /editor -->
</div><!-- /right -->

<script>
const PATHWAYS = ['retain','reuse','adaptiveReuse','refurbish','recycle','disposal','rehome','remanufacture','stewardship'];
const PATHWAY_COLORS = {
  retain:'#2a7d5a', reuse:'#1e6fb3', adaptiveReuse:'#7b4db8', refurbish:'#c98a1a',
  recycle:'#2a9d5c', disposal:'#c94040', rehome:'#3a86b8', remanufacture:'#a05cb8', stewardship:'#4a7ab8'
};

let currentId = null;
let assets = [];
let searchTimer = null;
let sortMode = '';

// ── Starred assets (editor's own list — separate from the portal's stars) ───
// Stored in this browser's localStorage for localhost:5001, keyed by asset id.
const STAR_KEY = 'r8-editor-starred-assets';
const STAR_FIRST_KEY = 'r8-editor-starred-first';
const STAR_SVG = '<svg viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"/></svg>';
let starred = new Set();
let starFirst = false;
try {
  const saved = JSON.parse(localStorage.getItem(STAR_KEY));
  if (Array.isArray(saved)) starred = new Set(saved);
  starFirst = localStorage.getItem(STAR_FIRST_KEY) === '1';
} catch (e) {}

function starBtnHtml(id) {
  const on = starred.has(id);
  return `<button class="star-btn${on ? ' on' : ''}" title="${on ? 'Unstar' : 'Star'}" onclick="event.stopPropagation();toggleStar('${id}')">${STAR_SVG}</button>`;
}
function toggleStar(id) {
  if (starred.has(id)) starred.delete(id); else starred.add(id);
  try { localStorage.setItem(STAR_KEY, JSON.stringify([...starred])); } catch (e) {}
  sortAssets();
  renderList();
  syncStarUi();
}
function toggleStarFirst() {
  starFirst = !starFirst;
  try { localStorage.setItem(STAR_FIRST_KEY, starFirst ? '1' : '0'); } catch (e) {}
  sortAssets();
  renderList();
  syncStarUi();
}
function syncStarUi() {
  const b = document.getElementById('btn-star-first');
  b.classList.toggle('on', starFirst);
  b.setAttribute('aria-pressed', starFirst ? 'true' : 'false');
  b.title = starFirst
    ? `Starred assets shown first (${starred.size}) — click to turn off`
    : `Show starred assets first (${starred.size} starred)`;
  document.getElementById('ed-star').innerHTML = currentId ? starBtnHtml(currentId) : '';
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function fetchList(q='') {
  const res = await fetch(`/api/assets?q=${encodeURIComponent(q)}`);
  assets = await res.json();
  sortAssets();
  renderList();
}

function sortAssets() {
  if (sortMode) sortByMode();
  // Array.sort is stable, so this keeps the chosen order within each group.
  if (starFirst) assets.sort((a, b) => starred.has(b.id) - starred.has(a.id));
}

function sortByMode() {
  assets.sort((a, b) => {
    const ta = a.title || '', tb = b.title || '';
    if (sortMode === 'title') return ta.localeCompare(tb);
    const ka = (sortMode === 'category' ? a.category : a.pathway) || '';
    const kb = (sortMode === 'category' ? b.category : b.pathway) || '';
    const c = ka.localeCompare(kb);
    return c !== 0 ? c : ta.localeCompare(tb);
  });
}

document.getElementById('sort-mode').addEventListener('change', e => {
  sortMode = e.target.value;
  sortAssets();
  renderList();
});

function renderList() {
  const el = document.getElementById('asset-list');
  document.getElementById('count-label').textContent = `${assets.length} asset${assets.length!==1?'s':''}`;
  el.innerHTML = assets.map((a, i) => {
    const next = assets[i + 1];
    const end = starFirst && starred.has(a.id) && next && !starred.has(next.id);
    const imgHtml = a.imageUrl
      ? `<img class="asset-thumb" src="${a.imageUrl}" onerror="this.style.display='none';this.nextSibling.style.display='flex'">`
        + `<div class="asset-thumb-placeholder" style="display:none">📦</div>`
      : `<div class="asset-thumb-placeholder">📦</div>`;
    const pw = a.pathway || '—';
    return `<div class="asset-row${a.id===currentId?' active':''}${end?' star-end':''}" onclick="loadAsset('${a.id}')">
      ${imgHtml}
      <div class="asset-info">
        <strong>${a.title}</strong>
        <span>${a.category || ''} · ${pw}</span>
      </div>
      <span style="margin-left:auto">${starBtnHtml(a.id)}</span>
    </div>`;
  }).join('');
}

// ── Load asset into editor ───────────────────────────────────────────────────
async function loadAsset(id) {
  currentId = id;
  renderList(); // update active highlight
  syncStarUi();
  const res = await fetch(`/api/assets/${id}`);
  const a = await res.json();
  populateEditor(a);
  document.getElementById('placeholder').style.display = 'none';
  document.getElementById('editor').style.display = 'block';
  setSaveStatus('');
}

function populateEditor(a) {
  document.getElementById('ed-title').textContent = a.title;
  document.getElementById('ed-meta').textContent = `ID ${a.id} · ${a.category} · ${a.primaryMaterialStream || ''}`;

  // Image
  const imgWrap = document.getElementById('ed-img-wrap');
  if (a.imageUrl) {
    imgWrap.innerHTML = `<img class="editor-img" src="${a.imageUrl}" onerror="this.parentNode.innerHTML='<div class=editor-img-ph>📦</div>'">`;
  } else {
    imgWrap.innerHTML = `<div class="editor-img-ph">📦</div>`;
  }
  renderPhotoGallery(a);

  // Core
  setVal('f-id', a.id);
  setVal('f-title', a.title);
  setVal('f-category', a.category);
  setVal('f-unit', a.unit);
  setVal('f-quantity', a.quantity);
  setVal('f-location', a.location);
  setVal('f-manufacturer', a.manufacturer);
  setVal('f-supplier', a.supplier);
  fillMaterialSelect(a.primaryMaterialStream || '');

  // Pathway
  const pw = a.pathway || {};
  setVal('f-pathway-suggested', pw.suggested);
  setVal('f-partners', (pw.partners||[]).join(', '));
  setVal('f-partners-supp', (pw.partnersSupplementary||[]).join(', '));

  // Weight
  const w = a.weight || {};
  setVal('f-weight-per', w.perUnit);

  // Dims
  const d = a.dimensions || {};
  setVal('f-dim-h', d.height);
  setVal('f-dim-d', d.depth);
  setVal('f-dim-w', d.width);

  // EC
  const ec = a.embodiedCarbon || {};
  setVal('f-ec-per', ec.perUnit);
  setVal('f-ec-src', ec.ecSource || 'estimate');

  // WE
  const we = a.wasteEmissions || {};
  setVal('f-we-factor', we.factor);
  setVal('f-we-src', we.efSource);

  // Notes
  setVal('f-notes-audit', (a.notes||{}).audit);
  setVal('f-notes-workshop', (a.notes||{}).workshop);

  // Trigger calculated fields
  recalc();

  // Pathway notes
  const pn = a.pathwayNotes || {};
  const grid = document.getElementById('pathway-notes-grid');
  grid.innerHTML = PATHWAYS.map(key => {
    const label = key.replace(/([A-Z])/g,' $1').replace(/^./,s=>s.toUpperCase());
    const color = PATHWAY_COLORS[key] || '#888';
    return `<div class="field">
      <label>
        <span class="pathway-badge" style="background:${color}22;color:${color}">${label}</span>
      </label>
      <textarea id="f-pn-${key}" placeholder="No note">${pn[key]||''}</textarea>
    </div>`;
  }).join('');
}

// ── Photos ───────────────────────────────────────────────────────────────────
function setHeaderThumb(a) {
  const imgWrap = document.getElementById('ed-img-wrap');
  imgWrap.innerHTML = a.imageUrl
    ? `<img class="editor-img" src="${a.imageUrl}" onerror="this.parentNode.innerHTML='<div class=editor-img-ph>📦</div>'">`
    : `<div class="editor-img-ph">📦</div>`;
  const listItem = assets.find(x => x.id === a.id);
  if (listItem) listItem.imageUrl = a.imageUrl;
  renderList();
}

function renderPhotoGallery(a) {
  const el = document.getElementById('photo-gallery');
  const imgs = (a.images && a.images.length) ? a.images : (a.imageUrl ? [a.imageUrl] : []);
  if (!imgs.length) {
    el.innerHTML = '<span class="photo-empty">No photos yet</span>';
    return;
  }
  el.innerHTML = imgs.map((u, i) => `
    <div class="photo-item${i===0?' cover':''}">
      <img src="${u}" onerror="this.style.opacity=0.15">
      <button class="photo-remove" title="Remove" onclick="removePhoto('${u}')">×</button>
      ${i>0 ? `<button class="photo-move left" title="Move earlier" onclick="movePhoto(${i},-1)">‹</button>` : ''}
      ${i<imgs.length-1 ? `<button class="photo-move right" title="Move later" onclick="movePhoto(${i},1)">›</button>` : ''}
    </div>
  `).join('');
}

async function uploadPhotos(files) {
  if (!currentId || !files || !files.length) return;
  const statusEl = document.getElementById('photo-upload-status');
  statusEl.textContent = 'Uploading…';
  statusEl.className = 'save-status';
  const fd = new FormData();
  Array.from(files).forEach(f => fd.append('photo', f));
  try {
    const res = await fetch(`/api/assets/${currentId}/images`, { method: 'POST', body: fd });
    const data = await res.json();
    if (data.ok) {
      statusEl.textContent = '✓ Added';
      statusEl.className = 'save-status save-ok';
      renderPhotoGallery(data.asset);
      setHeaderThumb(data.asset);
    } else {
      statusEl.textContent = 'Error: ' + (data.error || 'unknown');
      statusEl.className = 'save-status save-err';
    }
  } catch (e) {
    statusEl.textContent = 'Network error';
    statusEl.className = 'save-status save-err';
  }
}
document.getElementById('f-photo-upload').addEventListener('change', e => {
  uploadPhotos(e.target.files);
  e.target.value = '';
});

const dropzone = document.getElementById('photo-dropzone');
['dragenter','dragover'].forEach(ev => dropzone.addEventListener(ev, e => {
  e.preventDefault(); dropzone.classList.add('dragover');
}));
['dragleave','drop'].forEach(ev => dropzone.addEventListener(ev, e => {
  e.preventDefault(); dropzone.classList.remove('dragover');
}));
dropzone.addEventListener('drop', e => {
  const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
  uploadPhotos(files);
});
// Paste screenshots straight from the clipboard (Ctrl+V anywhere on the page)
window.addEventListener('paste', e => {
  const items = Array.from((e.clipboardData || {}).items || []);
  const files = items.filter(i => i.kind === 'file' && i.type.startsWith('image/'))
                     .map(i => i.getAsFile()).filter(Boolean);
  if (!files.length) return;   // plain-text paste into a field behaves as normal
  e.preventDefault();
  uploadPhotos(files);
});
// Stop a missed drop from navigating the browser away to the image
['dragover','drop'].forEach(ev => window.addEventListener(ev, e => e.preventDefault()));

async function removePhoto(path) {
  if (!currentId) return;
  if (!window.confirm('Remove this photo from the asset?\n\n(the file itself stays on disk — only the reference is removed)')) return;
  const res = await fetch(`/api/assets/${currentId}/images`, {
    method: 'DELETE',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path }),
  });
  const data = await res.json();
  if (data.ok) {
    renderPhotoGallery(data.asset);
    setHeaderThumb(data.asset);
  } else {
    alert('Remove failed: ' + (data.error || 'unknown'));
  }
}

async function movePhoto(i, dir) {
  if (!currentId) return;
  const res0 = await fetch(`/api/assets/${currentId}`);
  const a = await res0.json();
  const imgs = (a.images && a.images.length) ? a.images.slice() : (a.imageUrl ? [a.imageUrl] : []);
  const j = i + dir;
  if (j < 0 || j >= imgs.length) return;
  [imgs[i], imgs[j]] = [imgs[j], imgs[i]];
  const res = await fetch(`/api/assets/${currentId}`, {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ images: imgs, imageUrl: imgs[0] || null }),
  });
  const data = await res.json();
  if (data.ok) {
    renderPhotoGallery(data.asset);
    setHeaderThumb(data.asset);
  }
}

// ── Save ─────────────────────────────────────────────────────────────────────
async function saveAsset() {
  if (!currentId) return;
  const btn = document.getElementById('btn-save');
  btn.disabled = true;
  setSaveStatus('Saving…');

  const splitList = v => v ? v.split(',').map(s=>s.trim()).filter(Boolean) : [];
  const numOrNull = v => (v===''||v===null||v===undefined) ? null : Number(v);
  const strOrNull = v => (v===''||v===null||v===undefined) ? null : String(v).trim() || null;

  // Pathway notes
  const pn = {};
  PATHWAYS.forEach(key => {
    const el = document.getElementById(`f-pn-${key}`);
    pn[key] = strOrNull(el ? el.value : null);
  });

  const patch = {
    title: strOrNull(getVal('f-title')),
    category: getVal('f-category'),
    unit: getVal('f-unit'),
    quantity: numOrNull(getVal('f-quantity')),
    location: strOrNull(getVal('f-location')),
    manufacturer: strOrNull(getVal('f-manufacturer')),
    supplier: strOrNull(getVal('f-supplier')),
    primaryMaterialStream: strOrNull(getVal('f-pms')),
    pathway: {
      suggested: strOrNull(getVal('f-pathway-suggested')),
      partners: splitList(getVal('f-partners')),
      partnersSupplementary: splitList(getVal('f-partners-supp')),
    },
    dimensions: {
      height: numOrNull(getVal('f-dim-h')),
      depth:  numOrNull(getVal('f-dim-d')),
      width:  numOrNull(getVal('f-dim-w')),
    },
    weight: {
      perUnit: numOrNull(getVal('f-weight-per')),
      total:   numOrNull(getVal('f-weight-total')),  // calculated readonly
    },
    embodiedCarbon: {
      perUnit:  numOrNull(getVal('f-ec-per')),
      total:    numOrNull(getVal('f-ec-total')),      // calculated readonly
      ecSource: strOrNull(getVal('f-ec-src')),
    },
    wasteEmissions: {
      factor:    numOrNull(getVal('f-we-factor')),
      potential: numOrNull(getVal('f-we-pot')),       // calculated readonly
      efSource:  strOrNull(getVal('f-we-src')),
    },
    notes: {
      audit:    strOrNull(getVal('f-notes-audit')),
      workshop: strOrNull(getVal('f-notes-workshop')),
    },
    pathwayNotes: pn,
  };

  try {
    const res = await fetch(`/api/assets/${currentId}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(patch),
    });
    const data = await res.json();
    if (data.ok) {
      setSaveStatus('✓ Saved', true);
      loadMaterials();
      // Update list entry title
      const listItem = assets.find(a=>a.id===currentId);
      if (listItem) { listItem.title=patch.title; listItem.pathway=patch.pathway.suggested; }
      renderList();
      document.getElementById('ed-title').textContent = patch.title;
    } else {
      setSaveStatus('Error: ' + (data.error||'unknown'), false, true);
    }
  } catch(e) {
    setSaveStatus('Network error', false, true);
  }
  btn.disabled = false;
}

// ── Add new asset ────────────────────────────────────────────────────────────
async function addAsset() {
  const res = await fetch('/api/assets', {method:'POST'});
  const data = await res.json();
  if (data.ok) {
    await fetchList(document.getElementById('search').value);
    loadAsset(data.asset.id);
  }
}

// ── Utils ────────────────────────────────────────────────────────────────────
// ── Primary Material Stream dropdown ─────────────────────────────────────────
// Options = distinct values already in assets.json (same list as the portal's Material filter).
// "+ Add new material…" lets you introduce a new value; it joins the list once saved.
let materials = [];
const NEW_MATERIAL = '__new__';
function fillMaterialSelect(current) {
  const el = document.getElementById('f-pms');
  const keep = current !== undefined ? current : el.value;
  const opts = [...materials];
  if (keep && keep !== NEW_MATERIAL && !opts.includes(keep)) opts.push(keep);
  el.innerHTML = '<option value="">— none —</option>' +
    opts.map(m => `<option value="${m.replace(/"/g, '&quot;')}">${m}</option>`).join('') +
    `<option value="${NEW_MATERIAL}">+ Add new material…</option>`;
  el.value = keep || '';
  el.dataset.prev = el.value;
}
async function loadMaterials() {
  materials = await (await fetch('/api/materials')).json();
  fillMaterialSelect();
}
function onMaterialChange(el) {
  if (el.value !== NEW_MATERIAL) { el.dataset.prev = el.value; return; }
  const name = (prompt('New primary material stream (e.g. "Metal: Aluminium"):') || '').trim();
  if (!name) { el.value = el.dataset.prev || ''; return; }
  const existing = [...el.options].find(o => o.value.toLowerCase() === name.toLowerCase());
  if (existing) { el.value = existing.value; el.dataset.prev = el.value; return; }
  fillMaterialSelect(name);
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  const v = (val === null || val === undefined) ? '' : val;
  // Guard against a <select> silently discarding a value with no matching <option> —
  // that's exactly how the unit field got corrupted to '' on previous saves.
  if (el.tagName === 'SELECT' && v !== '' && ![...el.options].some(o => o.value === v)) {
    el.appendChild(new Option(v, v));
  }
  el.value = v;
}
function getVal(id) {
  const el = document.getElementById(id);
  return el ? el.value : null;
}
function setSaveStatus(msg, ok=false, err=false) {
  const el = document.getElementById('save-status');
  el.textContent = msg;
  el.className = 'save-status' + (ok?' save-ok':'') + (err?' save-err':'');
}

// ── Calculated fields ────────────────────────────────────────────────────────
function recalc() {
  const qty      = parseFloat(getVal('f-quantity'))   || 0;
  const wtPer    = parseFloat(getVal('f-weight-per')) || 0;
  const ecPer    = parseFloat(getVal('f-ec-per'))     || 0;
  const weFactor = parseFloat(getVal('f-we-factor'))  || 0;

  const wtTotal = qty * wtPer;
  const ecTotal = qty * ecPer;
  const wePot   = weFactor * wtTotal;   // factor (kgCO₂e/kg) × total kg

  document.getElementById('f-weight-total').value = wtTotal ? +wtTotal.toFixed(4) : '';
  document.getElementById('f-ec-total').value     = ecTotal ? +ecTotal.toFixed(4) : '';
  document.getElementById('f-we-pot').value        = wePot   ? +wePot.toFixed(6)  : '';
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function deleteAsset() {
  if (!currentId) return;
  const title = document.getElementById('ed-title').textContent;
  const confirm1 = window.confirm(`Delete "${title}"?\n\nThis will permanently remove the asset from assets.json. A backup will be made first.`);
  if (!confirm1) return;
  const typed = window.prompt(`Type the asset title exactly to confirm:\n\n${title}`);
  if (typed !== title) {
    if (typed !== null) alert('Title did not match — delete cancelled.');
    return;
  }
  const res = await fetch(`/api/assets/${currentId}`, { method: 'DELETE' });
  const data = await res.json();
  if (data.ok) {
    currentId = null;
    document.getElementById('editor').style.display = 'none';
    document.getElementById('placeholder').style.display = 'flex';
    setSaveStatus('');
    syncStarUi();
    await fetchList(document.getElementById('search').value);
  } else {
    alert('Delete failed: ' + (data.error || 'unknown'));
  }
}

// ── Search ───────────────────────────────────────────────────────────────────
document.getElementById('search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => fetchList(e.target.value), 220);
});

// ── Boot ──────────────────────────────────────────────────────────────────────
syncStarUi();
loadMaterials();
fetchList();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return HTML

# ── Launch ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = 5001
    # Check Flask is available
    pass

    print(f"\n  OPGG BRI Asset Editor")
    print(f"  ─────────────────────────────────────")
    print(f"  Running at  http://localhost:{port}")
    print(f"  Data file:  {DATA}")
    print(f"  Press Ctrl+C to stop\n")

    def open_browser():
        import time; time.sleep(1)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(port=port, debug=False)
