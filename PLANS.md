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

## 2b. Editing and approval workflow (owner decisions, 2026-11-27)

**Editor steps (UI built in the static portal; sending to a server is not built):**
1. Edit fields on the Edit Assets page (or the register's Review / edit card). Edits are **staged**. Moving between assets keeps them staged.
2. **Save changes** applies all staged edits in that browser (register, KPIs, home update) and keeps them there. **Discard** throws all staged edits away; nothing is written.
3. **Submit for review** sends the saved changes to the admins. In the preview this only marks them as submitted in the browser and says nothing is sent yet. It sits in the same bar as Save, and the header Edit Assets button shows a count badge while anything is saved or staged but not submitted. Signing out with unsubmitted changes asks for confirmation.

**Admin review (to build in the Next.js / AWS version):**
- Approvers: the owner, possibly one or two other team members. **One approval is enough.**
- Decide **each field individually** (accept / reject / skip). No batch-only approval needed.
- Each pending change shows the **initial value and the proposed value**. This also covers stale edits: if the data changed since the editor made their change, the admin still sees initial vs new and uses judgement.
- No rejection reason required (handled through other messaging channels). No withdraw option for editors for now.
- No trusted editors. Optional lightweight extra: admins can edit directly without going through review (source data can also be edited directly in the repo / owner's editor).
- Keep an audit log (who proposed, who decided, when) and data versioning so a bad merge can be undone.

## 2c. Shared login and the submission record (owner decisions, 2026-11-27)

**Constraint:** everyone is likely to share one login and password. There is therefore no way to know who submitted a change and no user-dependent pages or access. The portal cannot hold a private admin page: anyone with the password would see it. Review has to happen somewhere private.

**Proposed route (hosting colleague to confirm; Supabase is the working assumption):**
1. **Submit** sends the changes to a Supabase table (`submissions`). The browser's public key is limited by an **insert-only** row policy: it can add rows but cannot read, change or delete any.
2. **Review is private and local.** Either in the Supabase dashboard (Table Editor, no code) or, preferably, in a local admin tool (successor to `review_tool.py`) that downloads pending changes using a private key kept only on the owner's machine, never in the website. The tool shows original vs new per field; accept / reject each one individually.
3. **Apply:** accepted changes are written into `data/assets.json` locally (totals recalculated), committed and pushed; Amplify redeploys and everyone sees the update. The tool also marks the rows accepted / rejected in Supabase so they do not reappear.
4. Git as the inbox instead is only possible with a small server function in between (the browser cannot write to a repo). Supabase is simpler.

**Known limits with a shared login:** no submitter identity (none is collected); anyone with the password could send junk submissions. Every change still needs admin approval, so harm is limited; the database should reject malformed rows and can rate-limit inserts.

**Submission record: JSON.** In Supabase, one row per change with values stored as JSON.

*Submission (one per press of Submit):*

| Field | Meaning |
|---|---|
| `submission_id` | unique ID |
| `submitted_at` | timestamp (UTC) |
| `data_version` | which data the edits were based on |
| `change_count` | number of changes in it |

No submitter name or contact (decided: there is no way to verify it).

*Change (one per edited field):*

| Field | Meaning |
|---|---|
| `change_id` | unique ID |
| `submission_id` | the submission it belongs to |
| `asset_id` | the asset's ID |
| `asset_title` | its name, so the record is readable on its own |
| `field` | e.g. `quantity`, `pathway.suggested` |
| `field_label` | e.g. "Quantity" |
| `original_value` | what the submitter started from |
| `new_value` | what they changed it to |
| `value_type` | number, text or list |

*Review fields (filled in by the admin, not the submitter):*

| Field | Meaning |
|---|---|
| `status` | pending, accepted or rejected |
| `decided_at` | when the admin decided |
| `value_at_decision` | the live value at that moment (shows stale edits as initial vs new) |

Example payload:

```json
{
  "submission_id": "b3c1...",
  "submitted_at": "2026-11-27T04:12:09Z",
  "data_version": "a1b2c3d4e5f6a7b8",
  "change_count": 2,
  "changes": [
    { "asset_id": "4e287bba-...", "asset_title": "Air Diffuser - Louvre-faced",
      "field": "quantity", "field_label": "Quantity",
      "original_value": 90, "new_value": 7, "value_type": "number" }
  ]
}
```

## 3. Decisions still needed from the owner

- **Login credentials storage (important):** credentials and roles must NOT live in the page's source code (anyone can read it, and the data is sensitive). Options: Amplify's site-wide password (one shared credential, no roles) as a stopgap, or real accounts through AWS (Cognito) with roles checked on the server. Hosting colleague to advise. A front-end-only role switch is possible for UI testing but is not secure.

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

**Editable (22):** Quantity, Location, Manufacturer, Supplier, Primary material stream, Pathway, Primary partner(s), Supplementary partner(s), Weight per unit (kg), Height / Depth / Width (mm), Workshop notes, and all nine pathway notes (Retain, Reuse, Adaptive Reuse, Refurbish, Recycle, Dispose, Rehome, Remanufacture, Stewardship).

**Fixed (shown read-only; the merge tool also rejects them):** ID, Title, Category, Unit, Photos, EC per unit, EC source, WE factor, EF source, Audit notes.

**Automatic (calculated, never edited):** total weight, total embodied carbon, waste emissions potential. Recalculated from quantity, weight per unit, EC per unit and WE factor.

**Not on the owner's list, handled as follows (confirm):**
- Height / Depth / Width (mm): made **editable** (owner confirmed; not used in any calculation yet).
- `intoNewFitout`: kept in the data model, not editable. Not set on any asset right now.
- Add asset: not available to editors. Delete asset: admin only (owner's local editor, later the admin area).

**Removed (data hygiene):** `pathway.suggestedId` (unused lookup link), `pathwayConfirmed` (pre-defit audit, nothing confirmed yet; bring back when pathways are implemented), `excludeFromStats` (replaced by the Out-of-Scope category).

Later: per-role permissions (for example, some roles may edit only some of the 19). The field list is one array in `review.js` and one in `review_tool.py` in the static build; in the Next.js app it should be a single shared permissions table.
