# OPGG-BRI Portal: transfer checklist

This folder is a copy of the Chifley Tower portal (`chifley-pilot`), made to become the
**OPGG-BRI Portal**. Nothing here has been changed yet except this file. The `.git`
folder was deliberately **not** copied, so this project has no history and **no remote**:
it cannot be pushed to the Chifley repo by accident, and it will not go live until you
create a new repo and connect it to Amplify (see step 9).

The site is fully static (no backend, no build step). Everything is driven by `data/*.json`,
`Reports/index.json` and a handful of hard-coded Chifley values in the code.

## 1. Start a fresh repo (do this first)
```
git init
git add -A
git commit -m "Copy of Chifley portal as starting point"
```
Do not add a remote until the content has been replaced (step 9).

## 2. Clear Chifley-only content
Remove or empty these, they belong to the old project:
- `Reports/Floor Plans/`, `Reports/Miscellaneous/`, `Reports/Resource Recovery Report/`,
  `Reports/Chifley_Reused_OnSite_Items.xlsx`, and the old `Reports/Exports/` files
- `Reports/index.json`: reset to `[]` (keep the folder names you want, e.g. an empty
  "Downstream Documentation & Reporting" placeholder entry like the existing `ddr-folder`)
- `data/images/images_assets/` (asset photos), `data/images/Site Photos/`, and any
  Chifley-specific logos in `data/images/logos/`

## 3. Replace the data (`data/`)
| File | Action |
|------|--------|
| `assets.json` | Replace with the OPGG-BRI register. **Keep the same shape** (see below) |
| `partners.json` | New project team and recovery partners |
| `ald_report.json` | Only if the project has ALD data of the same type, otherwise empty/hide the ALD page |

Each asset record needs: `id`, `title`, `category` (Built Form / FF&E / Services),
`unit`, `quantity`, `primaryMaterialStream`, `weight.perUnit/total`,
`pathway.suggested` (+ `partners`), `embodiedCarbon` (`perUnit`, `ecSource`, `total`),
`wasteEmissions` (`factor`, `efSource`, `potential`), `pathwayNotes.*`,
`pathwayConfirmed`, `intoNewFitout`, `images`, `imageUrl`. Use
`data/assets.json` as the template. If the new register arrives in another format
(e.g. Excel), write a one-off converter into this shape rather than changing the portal.
The chart pages in `charts/` fetch the same `assets.json`, so they update automatically.

## 4. Rename and rebrand
Search for `Chifley`, `chifley` and `Charter Hall` (about 50 hits in the portal, plus a few in
`charts/*.html` and `README.md`):
- `chifley-portal.html`: rename the file (e.g. `opgg-bri-portal.html`), then update the
  redirect in `index.html`, the README, and `amplify.yml` comments. Edit the header comment,
  splash card (~line 41), hero heading (~line 115), project card and address (~lines 163-168),
  site photo path, Pathways blurb (~lines 821, 833), and the Export modal download links
  (~lines 1054, 1059).
- `app.js`: footer text (~1236), export subject/body (~1479-1525, `CONTACT_SUBJECT`,
  `CONTACT_EMAIL`), "Reused within the new Chifley fitout" label (~808), file header comment.
- `styles.css` (2 mentions), `charts/*.html` titles/labels (grep each).
- Page `<title>` and the README title.

## 5. Hard-coded Chifley values in the code (will NOT update from the data)
- `app.js:19`: `NLA_M2 = 793` (net lettable area, drives kg/m² figures)
- `app.js:~1013`: `LEED_TARGETED` material list; Benchmarks (LEED v5, Green Star, LBC)
  criteria and thresholds in the `tab-benchmarks` section of the HTML and `app.js`
  (~lines 979-1013). Redo these for the new project or hide the page
- Home page: project timeline dates, "About"/"Project" text, stats band
- `COLLECTIVE` partner logo list (`app.js:~1195`) and logos in `data/images/logos/`
- Pathways page: project team block and pathway partner names
- ALD Report page copy (only relevant if keeping ALD)

## 6. Hide pages that do not apply
Each page is a `nav-tab` button plus a `tab-*` div in the portal HTML. To drop one
(Benchmarks, ALD Report, Network), delete both and any home-page card that links to it.

## 7. Rebuild the downloadable exports
Both are generated from the data, so rerun after the new `assets.json` is in place.
Needs Python with `openpyxl`, `playwright`, `pypdf` (and Chrome for the PDF).
```
python scripts/export_asset_register.py
python scripts/build_report_pdf.py
```
- Update the output file names and the "Chifley" wording in both scripts and the
  `entry` titles/descriptions they write into `Reports/index.json`.
- `build_report_pdf.py` sets `SAMPLE_ROWS` (register sample length) and the page list. If
  pages are removed in step 6, remove them from the script's section list.
- Check the PDF by eye: page fit depends on the content height of each section.

## 8. Preview locally
Browsers block `fetch()` on `file://`, so serve the folder:
```
python -m http.server 3000
```
then open `http://localhost:3000/opgg-bri-portal.html` (or whatever the file is now called).
Check every tab, the Export modal (downloads work), and the Reports page.

## 9. Going live (only when ready)
1. Create a new empty repo (e.g. `refit8/opgg-bri-pilot`).
2. `git remote add origin <new repo url>` then push.
3. Create a **new** Amplify app connected to the new repo. `amplify.yml` needs no changes.
Do not reuse the Chifley Amplify app or repo.

## Quick find list
```
grep -rn -i "chifley\|charter hall\|the collective\|level 13\|NLA_M2\" --include=*.html --include=*.js --include=*.md --include=*.py --include=*.json . 
```
