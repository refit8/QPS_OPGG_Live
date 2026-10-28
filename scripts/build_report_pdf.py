"""Build Reports/Exports/OPGG-BRI_Portal_Report.pdf from the live portal pages.

Run from the repo root:  python scripts/build_report_pdf.py
Needs:  pip install playwright pypdf   (uses the locally installed Chrome)

Serves the repo on a local port, opens the portal headlessly, renders each
section to PDF with the interactive chrome (nav, filters, buttons, footers)
hidden, then merges the sections in order. Pre-built output is committed, so
this only needs re-running if the content changes.
"""
import functools
import http.server
import io
import json
import os
import threading
from datetime import date

from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "Reports", "Exports", "OPGG-BRI_Portal_Report.pdf")
SAMPLE_ROWS = 28

# Hide everything interactive or navigational, and let pages grow to full height
PAGE_CSS = """
html,body{height:auto!important;overflow:visible!important}
.app{display:block!important;height:auto!important}
.tab-page{overflow:visible!important;height:auto!important}
#r8-splash,nav.topnav,.dash-subnav,.site-footer-mount,.home-explore,.hh-actions,
.btn-export,.reg-btn,.rfile-btn{display:none!important}
html,body,.app,.tab-page,.tab-scroll{background:#fff!important}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.r8-widget,.r8-kpi,.ov-mini,.bm-card,.pw-card,.tl-step,tr{break-inside:avoid}
"""
# Inside the chart iframes: drop filters, toggles and export buttons
FRAME_CSS = """
html,body{background:#fff!important}
.filter-pill,#ghost-toggle,#export-btn,.export-btn,.chip,.cat-check,
.filters,.filter-bar,.controls,[class*="filter"],.chart-hint-bar,.hint{display:none!important}
"""

DISCLAIMER = (
    "This report is a static snapshot. Charts are shown without filters or "
    "tooltips. Visit the portal for the interactive graphs and the latest data."
)


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def update_index():
    """Keep the Reports page entry in step with the file."""
    idx_path = os.path.join(ROOT, "Reports", "index.json")
    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)
    entry = {
        "id": "exp-002",
        "title": "Portal Report (PDF)",
        "filename": os.path.basename(OUT),
        "category": "Exports",
        "date": date.today().isoformat(),
        "format": "PDF",
        "size": f"{os.path.getsize(OUT) / 1048576:.1f} MB",
        "path": "Reports/Exports/" + os.path.basename(OUT),
        "description": "Static snapshot of the portal: home, dashboard, asset register sample, "
                       "pathways and benchmarks. View the portal for interactive charts and the latest data.",
    }
    index = [e for e in index if e.get("id") != entry["id"]] + [entry]
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def main():
    srv = serve()
    url = f"http://127.0.0.1:{srv.server_port}/opgg-bri-portal.html"
    parts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script("sessionStorage.setItem('r8-splash-seen','1')")
        page.goto(url)
        page.wait_for_timeout(3000)
        page.add_style_tag(content=PAGE_CSS)

        def show(tab):
            page.evaluate(
                """t=>{document.querySelectorAll('.tab-page').forEach(p=>p.style.display='none');
                document.getElementById('tab-'+t).style.display='block'}""", tab)

        def style_frames():
            for fr in page.frames[1:]:
                try:
                    fr.add_style_tag(content=FRAME_CSS)
                except Exception:
                    pass

        def capture():
            page.wait_for_timeout(2000)
            style_frames()
            page.wait_for_timeout(500)
            # Shrink slightly to keep a section on one sheet; long pages just paginate
            height = page.evaluate("document.documentElement.scrollHeight")
            fit = 1085 / height
            scale = fit if 0.55 <= fit < 0.58 else 0.58
            data = page.pdf(format="A4", scale=scale, print_background=True,
                            margin={"top": "5mm", "bottom": "5mm", "left": "5mm", "right": "5mm"})
            parts.append(PdfReader(io.BytesIO(data)))

        def note(text):
            page.evaluate(
                """([id,t])=>{document.getElementById(id)?.remove();
                const d=document.createElement('div');d.id=id;
                d.style.cssText='margin:16px auto;max-width:1100px;padding:12px 16px;border:1px solid #e6c9a8;background:#fff7ee;border-radius:8px;font:15px/1.5 sans-serif;color:#4a3b2a';
                d.textContent=t;document.getElementById('tab-dashboard').prepend(d)}""",
                ["r8-pdf-note", text])

        # 1. Home
        show("home")
        capture()

        # 2. Dashboard: overview, then each sub-view
        show("dashboard")
        for view in ["all", "flow", "pyr", "outflow", "sust", "reuse"]:
            page.evaluate(f"setDashView(document.querySelector('.dash-subtab[data-view={view}]'))")
            # The portal's carbon-emissions disclaimer repeats under every chart: keep it once, on the last page
            page.evaluate(
                "d=>document.querySelectorAll('#tab-dashboard .disclaimer-bar').forEach(e=>e.style.display=d?'none':'')",
                view != "reuse")
            if view == "all":
                note(DISCLAIMER)
            else:
                page.evaluate("document.getElementById('r8-pdf-note')?.remove()")
            capture()

        # 3. Asset register sample
        show("register")  # keep register chrome off; replace with a sample table
        page.evaluate(
            """async ([n])=>{
              const raw=await (await fetch('data/assets.json')).json();
              const all=Array.isArray(raw)?raw:raw.assets;
              const rows=[...all].sort((a,b)=>b.weight.total-a.weight.total).slice(0,n);
              const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
              const tr=rows.map(a=>`<tr><td>${esc(a.title)}</td><td>${esc(a.category)}</td><td>${esc(a.primaryMaterialStream)}</td><td style="text-align:right">${a.quantity} ${esc(a.unit)}</td><td style="text-align:right">${a.weight.total.toLocaleString()}</td><td>${esc(a.pathway.suggested)}</td></tr>`).join('');
              document.querySelectorAll('.tab-page').forEach(p=>p.style.display='none');
              let s=document.getElementById('r8-pdf-reg');
              if(!s){s=document.createElement('div');s.id='r8-pdf-reg';document.querySelector('.app').append(s)}
              s.style.cssText='display:block;max-width:1100px;margin:0 auto;padding:36px 32px;font:16px/1.5 sans-serif;color:#1a1a2e';
              s.innerHTML=`<h2 style="font-size:28px;margin:0 0 6px">Asset Register: Sample</h2>
              <p style="margin:0 0 18px;color:#555">The ${n} heaviest of ${all.length} asset types by total weight. View the portal or the Excel export on the Reports page for the full asset register.</p>
              <table style="width:100%;border-collapse:collapse;font-size:14px">
              <thead><tr style="background:#1f2a44;color:#fff;text-align:left">${['Asset','Category','Material stream','Quantity','Total weight (kg)','Suggested pathway'].map(h=>`<th style="padding:8px 10px">${h}</th>`).join('')}</tr></thead>
              <tbody>${tr}</tbody></table>`;
              s.querySelectorAll('td').forEach(td=>td.style.cssText+='padding:7px 10px;border-bottom:1px solid #e5e5ea');
            }""", [SAMPLE_ROWS])
        capture()
        page.evaluate("document.getElementById('r8-pdf-reg').remove()")

        # 4. Remaining pages
        for tab in ["pathways", "benchmarks"]:
            show(tab)
            capture()

        browser.close()
    srv.shutdown()

    writer = PdfWriter()
    for r in parts:
        for pg in r.pages:
            writer.add_page(pg)
    writer.add_metadata({"/Title": "Olympic and Paralympic Games Accommodation Level 13: Circularity Pilot Report",
                         "/Author": "Refit8", "/CreationDate": date.today().isoformat()})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        writer.write(f)
    update_index()
    print(f"Wrote {os.path.relpath(OUT, ROOT)}: {len(writer.pages)} pages, {os.path.getsize(OUT)//1024} KB")


if __name__ == "__main__":
    main()
