"""
Build the offline REVIEW PACKAGE: a folder (optionally zipped) that reviewers open by
double-clicking, with no Python, server or internet needed for the portal itself.

    python scripts/build_review_package.py                  # web-sized images, version = today + letter
    python scripts/build_review_package.py --images full    # original images (very large)
    python scripts/build_review_package.py --zip            # also write a .zip next to the folder
    python scripts/build_review_package.py --version 2026-11-12-a --max-edge 1200

What it does
  * copies the portal (html / app.js / styles.css / review.js), only the charts the portal uses, and the logos
  * makes the package fully offline: vendor/ (d3, Chart.js and the Geist / Chivo Mono fonts, saved locally),
    the shared chart stylesheet + its fonts, and the charts are pointed at vendor/ instead of the CDN.
    The Partner Network map tab (live Leaflet / OpenStreetMap, no menu button) is left out of the package.
    verify_package() fails the build if any script, stylesheet or font is missing or loads from the internet
  * embeds data/assets.json, partners.json, ald_report.json into package-data.js, because
    browsers block fetch() on file:// pages
  * writes review-config.js, which switches review mode ON and stamps the data version + hash
  * copies the asset photos the register uses (resized unless --images full)
  * saves a base snapshot of assets.json in review/bases/<version>.json so submissions can
    be checked against exactly what was shared
The live site is never touched: review mode only exists inside the package.
"""
import argparse, datetime, hashlib, json, os, re, shutil, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["pathway.suggested", "pathway.partners", "pathway.partnersSupplementary",
          "notes.workshop", "manufacturer", "supplier"]


IMG_REF = re.compile(r"""data/images/[^"'`)\\\r\n]+?\.(?:png|jpe?g|webp|gif|svg)""", re.I)


# Referenced by the portal's CSS but absent from the source project too (already broken on the live site).
# Listed so they do not fail every build; remove an entry once the file exists or the reference is deleted.
KNOWN_MISSING_IN_SOURCE = {
    "data/images/Site Photos/Chifley1.jpeg",             # styles.css .home-hero background (hidden under a gradient)
    "data/images/logos/Refit8_monogram_outline.png",     # styles.css .r8-monogram watermark
}


def page_image_refs(out):
    """{decoded path: file that references it} for every data/images/... path named in the package's html/js/css."""
    from urllib.parse import unquote
    refs = {}
    for f in out.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".html", ".js", ".css"):
            for m in IMG_REF.findall(f.read_text(encoding="utf-8", errors="ignore")):
                if "${" not in m and "+" not in m:      # built at run time, cannot be checked statically
                    refs.setdefault(unquote(m), f.name)
    return refs


def copy_referenced(out, max_edge):
    """Charts embed their own image lists, so copy any image the pages name that exists in the source."""
    n = 0
    for r in sorted(page_image_refs(out)):
        if not (out / r).is_file() and (ROOT / r).is_file():
            copy_image(ROOT / r, out / r, max_edge); n += 1
    if n:
        print(f"Also copied {n} image(s) named by the charts/CSS but not listed in assets.json")


# Libraries the charts load from a CDN on the live site. In the package they are read from vendor/ instead,
# so no internet is needed. {CDN url: file in vendor/}
CDN_TO_VENDOR = {
    "https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js": "d3.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/d3-sankey/0.12.3/d3-sankey.min.js": "d3-sankey.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js": "chart.umd.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-datalabels/2.2.0/chartjs-plugin-datalabels.min.js":
        "chartjs-plugin-datalabels.min.js",
}
GOOGLE_FONTS_LINKS = re.compile(
    r'[ \t]*<link rel="preconnect" href="https://fonts\.(?:googleapis|gstatic)\.com"[^>]*>\r?\n'
    r'|[ \t]*<link href="https://fonts\.googleapis\.com/css2[^"]*" rel="stylesheet">\r?\n')
NETWORK_TAB = re.compile(r'<!-- ══ PARTNER NETWORK TAB ══.*?<!-- /tab-network -->[ \t]*\r?\n', re.S)


def localise_portal_html(html):
    """Package-only changes to the portal page: fonts come from vendor/, and the Partner Network tab
    (a live Leaflet/OpenStreetMap map that needs the internet and has no menu button) is left out."""
    assert GOOGLE_FONTS_LINKS.search(html), "could not find the Google Fonts links in the portal html"
    first = True
    def swap(m):
        nonlocal first
        if first:
            first = False
            return '<link rel="stylesheet" href="vendor/fonts.css">\n'
        return ""
    html = GOOGLE_FONTS_LINKS.sub(swap, html)
    html, n = NETWORK_TAB.subn("", html)
    assert n == 1, "could not find the Partner Network tab block in the portal html"
    return html


# Added to every chart page in the package. The portal normally reads each chart's height to size its frame, but
# browsers block that between file:// pages (each file is its own origin), which clipped the taller charts at
# their minimum height. The chart now tells the portal its height with postMessage, which works from disk.
# Only pages with a .wrap element report (same rule as the portal: without one, body height just echoes the frame).
HEIGHT_SENDER = (b"<script>/* review package: report chart height to the portal */(function(){"
                 b"function send(){var d=document,t=d.querySelector('.topbar'),w=d.querySelector('.wrap');if(!w||parent===window)return;"
                 b"parent.postMessage({type:'r8-chart-height',height:(t?t.offsetHeight:0)+w.scrollHeight},'*');}"
                 b"[100,400,900,1800,3500].forEach(function(ms){setTimeout(send,ms);});window.addEventListener('load',send);"
                 b"var w=document.querySelector('.wrap');if(w&&window.ResizeObserver)new ResizeObserver(function(){setTimeout(send,120);}).observe(w);"
                 b"})();</script>\n")


def copy_offline_assets(out):
    """vendor/ (chart libraries + local fonts) and the shared chart stylesheet with the fonts it names."""
    shutil.copytree(ROOT / "vendor", out / "vendor")
    rewritten = 0
    for c in (out / "charts").glob("*.html"):
        b = c.read_bytes(); orig = b
        for url, name in CDN_TO_VENDOR.items():
            b = b.replace(url.encode(), f"../vendor/{name}".encode())
        i = b.rfind(b"</body>")
        assert i != -1, f"no </body> in {c.name}: cannot add the height sender"
        b = b[:i] + HEIGHT_SENDER + b[i:]
        if b != orig:
            c.write_bytes(b); rewritten += 1
    css_src = ROOT / "Refit8_dashboard_mockup" / "shared.css"
    css_dst = out / "Refit8_dashboard_mockup" / "shared.css"
    css_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(css_src, css_dst)
    fonts = 0
    for ref in set(re.findall(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', css_src.read_text(encoding="utf-8"))):
        if ref.startswith(("data:", "http")): continue
        src = css_src.parent / ref
        if src.is_file():
            (out / "Refit8_dashboard_mockup" / ref).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out / "Refit8_dashboard_mockup" / ref); fonts += 1
    print(f"Offline assets: vendor/ copied, {rewritten} chart page(s) updated (local libraries + height reporting), "
          f"shared.css + {fonts} font file(s) copied")


ATTR_REF = re.compile(r"""<(script|link|iframe)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["'][^>]*>""", re.I)
CSS_REF = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)|@import\s+["']([^"']+)["']""", re.I)
LOADING_LINK = re.compile(r"""\brel\s*=\s*["'](?:stylesheet|icon|shortcut icon)["']""", re.I)
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico")


def check_resources(out):
    """Every <script src>, stylesheet/icon <link> and <iframe src> in the html, and every CSS url()/@import,
    must be a file that exists in the package. Anything that points at the internet is a failure: the
    package has to work offline. (Images are checked separately; <a> links are not resource loads.)"""
    from urllib.parse import unquote, urlsplit
    problems, n = [], 0
    for f in out.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in (".html", ".css"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        refs = []
        if f.suffix.lower() == ".html":
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)        # ignore commented-out markup
            for tag in ATTR_REF.finditer(text):
                whole = tag.group(0)
                if tag.group(1).lower() == "link" and not LOADING_LINK.search(whole):
                    continue                                          # preconnect etc. do not load a file
                refs.append(tag.group(2))
            for style in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I):
                refs += [a or b for a, b in CSS_REF.findall(style)]
        else:
            refs += [a or b for a, b in CSS_REF.findall(text)]
        for ref in refs:
            ref = ref.strip()
            if not ref or ref.startswith(("data:", "#", "mailto:", "javascript:")) or "${" in ref or "+" in ref:
                continue
            n += 1
            if ref.startswith(("http://", "https://", "//")):
                problems.append(f"EXTERNAL {ref}   (loaded by {f.relative_to(out)})")
                continue
            path = unquote(urlsplit(ref).path)
            if path.lower().endswith(IMG_EXT):
                continue                                              # covered by page_image_refs
            if not (f.parent / path).resolve().is_file():
                problems.append(f"MISSING {ref}   (referenced in {f.relative_to(out)})")
    return n, problems


def verify_package(out):
    """Fail loudly if the page references an image, stylesheet, script or font that is not in the package,
    if anything would be loaded from the internet, or if two files would collide on a
    case-insensitive file system (Windows / macOS)."""
    problems = []
    n_res, res_problems = check_resources(out)
    problems += res_problems
    print(f"Verify: {n_res} script/stylesheet/font references checked, {len(res_problems)} problem(s)")
    refs = page_image_refs(out)
    for r in sorted(refs):
        if not (out / r).is_file():
            if r in KNOWN_MISSING_IN_SOURCE:
                print(f"  (known gap, not in source either: {r})")
            else:
                problems.append(f"MISSING {r}   (referenced in {refs[r]})")
    seen = {}
    for f in out.rglob("*"):
        if f.is_file():
            k = str(f.relative_to(out)).lower()
            if k in seen:
                problems.append(f"NAME COLLISION {f.relative_to(out)} / {seen[k]}")
            seen[k] = f.relative_to(out)
    print(f"Verify: {len(refs)} image references checked, "
          f"{sum(p.startswith('MISSING') for p in problems) - sum(p.startswith('MISSING') for p in res_problems)} missing")
    if problems:
        print("\n".join("  ! " + p for p in problems))
        sys.exit("BUILD FAILED: the package is incomplete. Nothing was zipped.")


def verify_zip(zp, out):
    """Re-open the finished zip and check every package file is in it with the right size."""
    with zipfile.ZipFile(zp) as z:
        bad = z.testzip()
        if bad:
            sys.exit(f"BUILD FAILED: zip is corrupt at {bad}")
        got = {i.filename: i.file_size for i in z.infolist() if not i.is_dir()}
    want = {(Path(out.name) / f.relative_to(out)).as_posix(): f.stat().st_size for f in out.rglob("*") if f.is_file()}
    miss = sorted(set(want) - set(got)); wrong = sorted(k for k in want if k in got and got[k] != want[k])
    if miss or wrong:
        print("\n".join(["  ! not in zip: " + m for m in miss[:20]] + ["  ! wrong size: " + w for w in wrong[:20]]))
        sys.exit("BUILD FAILED: the zip does not match the package folder.")
    n_img = sum("/images_assets/" in k for k in got)
    print(f"Zip verified: {len(got)} files ({n_img} asset photos), all present and the right size")


def used_charts(portal_html):
    """Chart files the portal opens, plus any chart those charts link to. Unused charts are left out of the package."""
    pat = re.compile(r"\b(\d{2}_[A-Za-z0-9_]+\.html)")
    seed = set(pat.findall(portal_html))
    for f in ("app.js", "review.js"):
        seed |= set(pat.findall((ROOT / f).read_text(encoding="utf-8")))
    keep, todo = set(), [c for c in seed if (ROOT / "charts" / c).exists()]
    while todo:
        c = todo.pop()
        if c in keep: continue
        keep.add(c)
        todo += [m for m in pat.findall((ROOT / "charts" / c).read_text(encoding="utf-8"))
                 if m not in keep and (ROOT / "charts" / m).exists()]
    return keep


def next_version(today):
    bases = ROOT / "review" / "bases"
    n = 0
    while (bases / f"{today}-{chr(97 + n)}.json").exists() and n < 25:
        n += 1
    return f"{today}-{chr(97 + n)}"


def copy_image(src: Path, dst: Path, max_edge):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not max_edge:
        shutil.copy2(src, dst); return
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if max(im.size) <= max_edge:
                shutil.copy2(src, dst); return
            im.thumbnail((max_edge, max_edge), Image.LANCZOS)
            ext = src.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                im.convert("RGB").save(dst, "JPEG", quality=82, optimize=True)
            elif ext == ".png":
                im.save(dst, "PNG", optimize=True)
            else:
                im.save(dst)
    except Exception as e:                     # never lose an image because resizing failed
        print(f"  ! could not resize {src.name} ({e}); copied as is")
        shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="package/data version stamp (default: today + a letter)")
    ap.add_argument("--out", help="output folder (default: dist/review_package_<version>)")
    ap.add_argument("--images", choices=["web", "full"], default="web")
    ap.add_argument("--max-edge", type=int, default=1400, help="longest image edge in px for --images web")
    ap.add_argument("--zip", action="store_true", help="also create a .zip of the package")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    version = args.version or next_version(today)
    out = Path(args.out) if args.out else ROOT / "dist" / f"review_package_{version}"
    if out.exists():
        sys.exit(f"Output folder already exists: {out}\nPick another --version/--out, or delete it first.")

    assets_path = ROOT / "data" / "assets.json"
    raw = assets_path.read_bytes()
    assets = json.loads(raw.decode("utf-8"))
    ahash = hashlib.sha256(raw).hexdigest()[:16]

    out.mkdir(parents=True)
    print(f"Building review package {version} -> {out}")

    # ── portal files ──
    for f in ("app.js", "styles.css", "review.js", "index.html"):
        shutil.copy2(ROOT / f, out / f)
    html = localise_portal_html((ROOT / "opgg-bri-portal.html").read_text(encoding="utf-8"))
    tag ='<script src="review-config.js"></script>\n<script src="package-data.js"></script>\n<script src="review.js" defer></script>\n'
    needle = '<script src="app.js" defer></script>'
    assert html.count(needle) == 1, "could not find the app.js script tag in opgg-bri-portal.html"
    (out / "opgg-bri-portal.html").write_text(html.replace(needle, tag + needle), encoding="utf-8")

    used = used_charts(html)
    (out / "charts").mkdir()
    for c in sorted(used):
        shutil.copy2(ROOT / "charts" / c, out / "charts" / c)
    skipped = sorted(p.name for p in (ROOT / "charts").iterdir() if p.is_file() and p.name not in used)
    print(f"Charts: {len(used)} included; left out (not in the portal): {', '.join(skipped) or 'none'}")
    copy_offline_assets(out)
    for sub in ("logos", "Sketches"):
        if (ROOT / "data" / "images" / sub).exists():
            shutil.copytree(ROOT / "data" / "images" / sub, out / "data" / "images" / sub)
    for f in ("Refit8_asset_isometric.webp",):
        if (ROOT / "data" / "images" / f).exists():
            shutil.copy2(ROOT / "data" / "images" / f, out / "data" / "images" / f)

    # ── embedded data + config ──
    emb = {"data/assets.json": assets,
           "data/partners.json": json.loads((ROOT / "data" / "partners.json").read_text(encoding="utf-8")),
           "Reports/index.json": []}
    ald = ROOT / "data" / "ald_report.json"
    if ald.exists():
        emb["data/ald_report.json"] = json.loads(ald.read_text(encoding="utf-8"))
    (out / "package-data.js").write_text(
        "/* Embedded data for the offline review package (generated) */\nwindow.R8_EMBEDDED = "
        + json.dumps(emb, ensure_ascii=False) + ";\n", encoding="utf-8")
    cfg = {"enabled": True, "baseVersion": version, "assetsHash": ahash,
           "builtAt": datetime.datetime.now().isoformat(timespec="seconds"), "editableFields": FIELDS}
    (out / "review-config.js").write_text(
        "/* Review mode switch (generated). Delete this file to turn review mode off. */\nwindow.R8_REVIEW = "
        + json.dumps(cfg, indent=2) + ";\n", encoding="utf-8")

    # ── images used by the register ──
    paths = sorted({p for a in assets for p in ([a.get("imageUrl")] + (a.get("images") or [])) if p})
    max_edge = None if args.images == "full" else args.max_edge
    missing = 0
    before = after = 0
    for rel in paths:
        src = ROOT / rel
        if not src.exists():
            missing += 1; print(f"  ! missing image: {rel}"); continue
        dst = out / rel
        copy_image(src, dst, max_edge)
        before += src.stat().st_size; after += dst.stat().st_size
    print(f"Images: {len(paths) - missing} copied ({before/1e6:.0f} MB -> {after/1e6:.0f} MB)"
          + (f", {missing} missing" if missing else ""))

    # ── instructions + base snapshot ──
    (out / "README - START HERE.txt").write_text(
f"""OPGG-BRI PORTAL: REVIEW PACKAGE  (version {version})
==============================================================

HOW TO OPEN
  1. If this came as a zip, right-click it and choose Extract All first. Do not run it from inside the zip.
  2. Double-click  index.html  (or opgg-bri-portal.html). It opens in your browser. Chrome or Edge is best.
     No installation and no internet connection are needed for the register.
  3. Keep the folder where it is. Do not rename or move files inside it.

HOW TO REVIEW
  1. Go to the Asset Register and click any asset. Its details open on the right. Scroll to the bottom of
     that panel and click "Review / edit this asset" to open the orange "Review edits" box.
  2. You can edit six things: Pathway, Primary partner(s), Supplementary partner(s), Workshop notes,
     Manufacturer and Supplier. Everything else is read-only.
       - Partners are free text; separate several names with commas.
       - Clearing a box and leaving it empty removes that value.
       - Anything else you want changed (for example a quantity) cannot be edited directly. Describe it in the
         Workshop notes box instead and it will be picked up in review.
       - "Revert" under a field puts the original back.
  3. Your edits save in this browser automatically, so you can close it and come back. Edited assets are marked
     with an orange edge in the register.
  4. Click the star at the top of an asset's detail panel to flag any asset you want the quantities double-checked
     on. Your starred assets are included in your export. (Starring is optional.)

SENDING YOUR CHANGES BACK
  1. Click  Export changes  in the bar at the bottom-left of the page.
  2. Save the file (review_<date>_<time>.json) into the shared Submissions folder.
     (If your browser just downloads it, move it from Downloads to that folder.)
  3. Export again any time you make more changes. Each export is a complete list of everything you have
     changed, so the newest file is the one to use.

NOTES
  - Use the same browser on the same computer for the whole review, or your saved edits will not be there.
  - "Reset" throws away all your edits; export first if you want to keep them.
  - Everything, including the charts and fonts, is inside this folder. No internet connection is needed.
""", encoding="utf-8")
    snap = ROOT / "review" / "bases"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / f"{version}.json").write_bytes(raw)

    copy_referenced(out, max_edge)
    verify_package(out)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Package size: {size/1e6:.0f} MB   data hash: {ahash}")
    print(f"Base snapshot saved: {snap / (version + '.json')}")
    if args.zip:
        zp = out.with_suffix(".zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.rglob("*")):
                if f.is_file(): z.write(f, Path(out.name) / f.relative_to(out))
        print(f"Zip written: {zp} ({zp.stat().st_size/1e6:.0f} MB)")
        verify_zip(zp, out)
    print("Done.")


if __name__ == "__main__":
    main()
