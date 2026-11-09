"""Build Reports/Exports/OPGG-BRI_Asset_Register.xlsx from data/assets.json.

Run from the repo root:  python scripts/export_asset_register.py
Photos and estimated emissions values are deliberately excluded.
Also refreshes the matching entry in Reports/index.json.
"""
import json
import os
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_REL = "Reports/Exports/OPGG-BRI_Asset_Register.xlsx"
OUT = os.path.join(ROOT, OUT_REL)

COLUMNS = [
    ("Asset Name", lambda a: a["title"], 36),
    ("Category", lambda a: a["category"], 14),
    ("Primary Material Stream", lambda a: a["primaryMaterialStream"], 36),
    ("Unit", lambda a: a["unit"], 18),
    ("Quantity", lambda a: a["quantity"], 10),
    ("Total Weight (kg)", lambda a: a["weight"]["total"], 18),
    ("Suggested Pathway", lambda a: a["pathway"]["suggested"], 20),
]

with open(os.path.join(ROOT, "data/assets.json"), encoding="utf-8") as f:
    data = json.load(f)
assets = data if isinstance(data, list) else data["assets"]

wb = Workbook()
ws = wb.active
ws.title = "Asset Register"
ws.append([c[0] for c in COLUMNS])
for a in assets:
    ws.append([c[1](a) for c in COLUMNS])

hdr_fill = PatternFill("solid", fgColor="1F2A44")
for i, (name, _, width) in enumerate(COLUMNS, 1):
    cell = ws.cell(row=1, column=i)
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = hdr_fill
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.column_dimensions[get_column_letter(i)].width = width
ws.freeze_panes = "A2"
ws.auto_filter.ref = ws.dimensions
for row in ws.iter_rows(min_row=2, min_col=5, max_col=6):
    for cell in row:
        cell.number_format = "#,##0.0##" if cell.column == 6 else "#,##0.##"

about = wb.create_sheet("About")
# Out-of-Scope assets stay listed on the register sheet but are not counted anywhere
oos_n = sum(1 for a in assets if a["category"] == "Out-of-Scope")
rows = [
    ("Olympic and Paralympic Games Accommodation Level 13: Asset Register", ""),
    ("Generated", date.today().isoformat()),
    ("Assets", len(assets) - oos_n),
    ("Source", "Olympic and Paralympic Games Accommodation portal (data/assets.json)"),
    ("Notes", "Photos and estimated emissions values are excluded. "
              "View the portal for the latest data, images and interactive charts."),
]
if oos_n:
    rows.insert(3, ("Out-of-scope", f"{oos_n} further item(s) are listed on the register sheet for completeness "
                                    "but are excluded from all counts and totals."))
for r in rows:
    about.append(r)
about["A1"].font = Font(bold=True, size=14)
for r in range(2, len(rows) + 1):
    about.cell(row=r, column=1).font = Font(bold=True)
    about.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
about.column_dimensions["A"].width = 14
about.column_dimensions["B"].width = 80

wb.save(OUT)

# Keep the Reports page index in step with the file
idx_path = os.path.join(ROOT, "Reports/index.json")
with open(idx_path, encoding="utf-8") as f:
    index = json.load(f)
size_kb = round(os.path.getsize(OUT) / 1024)
entry = {
    "id": "exp-001",
    "title": "Asset Register (Excel)",
    "filename": os.path.basename(OUT),
    "category": "Exports",
    "date": date.today().isoformat(),
    "format": "XLSX",
    "size": f"{size_kb} KB",
    "path": OUT_REL,
    "description": "Full asset register without photos or estimated emissions values. "
                   "View the portal for the latest data.",
}
index = [e for e in index if e.get("id") != entry["id"]]
index.append(entry)
with open(idx_path, "w", encoding="utf-8") as f:
    json.dump(index, f, indent=2, ensure_ascii=False)
print(f"Wrote {OUT_REL}: {len(assets)} assets, {size_kb} KB")
