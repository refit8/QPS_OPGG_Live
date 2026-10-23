# OPGG-BRI Portal

Material intelligence portal for the OPGG-BRI defit. Built by Refit8 for Charter Hall.

This is a fully static site — no backend, no build step. `opgg-bri-portal.html` fetches
`data/assets.json`, `data/partners.json`, and `data/ald_report.json` at runtime via relative
paths, and embeds the pages under `charts/` as iframes. `index.html` just redirects to
`opgg-bri-portal.html` so the site has a sensible root route.

## Local preview

Browsers block `fetch()` on `file://` URLs, so don't open `opgg-bri-portal.html` directly —
serve the folder instead:

```
npx serve -l 3000
```

or

```
python3 -m http.server 3000
```

then visit `http://localhost:3000/opgg-bri-portal.html`.

## Deploying

No build step — `amplify.yml` in this repo tells AWS Amplify Hosting to skip the build phase
and publish the repo contents as-is. Connect this repo to an Amplify app and it will deploy on
every push to the connected branch.

## Structure

| Path | What it is |
|------|------------|
| `opgg-bri-portal.html` | The portal's markup — links `styles.css` and `app.js` |
| `styles.css` | All portal styling |
| `app.js` | All portal logic (data loading, rendering, interactions) |
| `data/assets.json` | Asset inventory — primary data source |
| `data/partners.json` | Partner network and project team |
| `data/ald_report.json` | ALD Resource Recovery report line items |
| `data/images/` | Asset photography and site photos |
| `charts/` | Individual chart pages, embedded in the portal as iframes |
| `Reports/` | Document repository (PDFs and supporting files) |
| `Refit8_dashboard_mockup/shared.css` + `Refit8 Design System/` | Brand design tokens, fonts, logos |
