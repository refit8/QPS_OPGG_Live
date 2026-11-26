# QPS_OPGG_Live: plans

Status: planning notes. Nothing here is built except where marked **Built**.
Owner decides UI, edit workflow and back-end handling of changes. Hosting and AWS
set-up is handled by a colleague. This file is the hand-over.

---

## 1. Where things stand

**Built (static portal, `opgg-bri-portal.html`, `app.js`, `review.js`)**
- Asset Register > **Edit Assets** page (also the header **Edit Assets** button). Search, sort (Title / Category / Pathway), star and star-first (shared with the register).
- Quick-edit card in the register detail panel (six fields).
- Edits show immediately in the editor's own browser and are stored there only (localStorage). The real data (`data/assets.json`) is not changed.
- Totals recalculate on edit (weight total, embodied carbon total, waste emissions potential).
- Edits that the owner later merges drop out of the browser automatically.
- Owner-side merge: `review_tool.py` (tick/cross per change), run locally via `edit_assets.py` at `localhost:5001/review`. Backs up and logs before writing.
- Not built: any way for a visitor's edits to reach the owner (the export bar was removed). This needs the back end below.

**Known gaps in the static version**
- Dashboard charts (iframes) read `assets.json` themselves, so they do not show browser edits.
- No photo upload, add asset or delete asset in the in-portal editor.
- `amplify.yml` publishes `**/*`, so Python scripts, `review/` and backups are downloadable from the live URL. Fix before or when going live.

---

## 2. Target architecture (Next.js + AWS)

1. **Login (Cognito).** Roles: `viewer`, `editor`, `admin`. Only the owner is `admin`. Per-field limits for editors become a setting on the role.
2. **Database for assets** (Postgres suits this structured data and audit queries; DynamoDB is the cheaper, Amplify-friendly alternative). Assets are rows/documents, not a file.
3. **Proposals table.** One row per proposed change: asset id, field, old value, new value, proposer, timestamp, status (`pending`, `accepted`, `rejected`), decided by, decided at, optional comment.
4. **Editing flow.** The Edit Assets page works as now, but Save calls a server API. The server checks role and field permission, validates the value, stores a pending proposal. The live asset is not touched. The editor still sees their own pending value straight away.
5. **Admin review page** (replaces `review_tool.py`). Admin-only page in the portal: pending changes with old/new values and source. Accept applies the change on the server, recalculates totals, logs who and when. Reject closes it. Everyone sees accepted changes. Competing proposals for the same field are flagged.
6. **Server enforcement.** Never trust the browser. The accept endpoint checks the admin role. Writes are logged; data is versioned so a bad merge can be undone.
7. **Photos** in S3 with signed URLs. Add / delete asset become admin-only actions.
8. **Hosting:** Next.js on Amplify. Local Python tools are not deployed.

**Carries over from the static build:** the field list, validation rules (number checks, known category/unit/pathway, title and category cannot be blank), the totals formulas, and the Edit Assets / star / review-card UI.

**Suggested order**
1. Commit the static portal to the new repo as the baseline.
2. Scaffold Next.js, port the pages.
3. Cognito login and roles.
4. Database for assets and proposals.
5. Admin review page.
6. Photos, add/delete, per-field permissions.

---

## 3. Decisions still needed from the owner

- **Approval model:** does every editor change need admin approval, or can trusted users change some fields directly?
- **Editable fields:** see section 4 (owner to mark each field).
- **Editor identity:** show proposer name on each change in the review page? (Recommended: yes.)
- **Rejected edits:** should the proposer see that a change was rejected, with a reason?
- **Withdrawing:** can an editor withdraw their own pending change?
- **Simultaneous edits:** if two people propose different values for one field, admin picks one (current behaviour) or newest wins?
- **Charts:** should dashboard charts show pending changes to the editor, or only accepted data? (Recommended: accepted data only.)
- **Database:** Postgres or DynamoDB (for the hosting colleague to confirm).
- **Repo:** fresh single-commit history or keep history (repo is about 1.2 GB; GitHub rejects single files over 100 MB).

---

## 4. Field decisions (owner, 2026-11-27)

**Editable (19):** Quantity, Location, Manufacturer, Supplier, Primary material stream, Pathway, Primary partner(s), Supplementary partner(s), Weight per unit (kg), Workshop notes, and all nine pathway notes (Retain, Reuse, Adaptive Reuse, Refurbish, Recycle, Dispose, Rehome, Remanufacture, Stewardship).

**Fixed (shown read-only; the merge tool also rejects them):** ID, Title, Category, Unit, Photos, EC per unit, EC source, WE factor, EF source, Audit notes.

**Automatic (calculated, never edited):** total weight, total embodied carbon, waste emissions potential. Recalculated from quantity, weight per unit, EC per unit and WE factor.

**Not on the owner's list, handled as follows (confirm):**
- Height / Depth / Width (mm): treated as **fixed** for now.
- `intoNewFitout`: kept in the data model, not editable. Not set on any asset right now.
- Add asset: not available to editors. Delete asset: admin only (owner's local editor, later the admin area).

**Removed (data hygiene):** `pathway.suggestedId` (unused lookup link), `pathwayConfirmed` (pre-defit audit, nothing confirmed yet; bring back when pathways are implemented), `excludeFromStats` (replaced by the Out-of-Scope category).

Later: per-role permissions (for example, some roles may edit only some of the 19). The field list is one array in `review.js` and one in `review_tool.py` in the static build; in the Next.js app it should be a single shared permissions table.
