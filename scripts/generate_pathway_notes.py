"""
Draft a defit + pathway note for every asset, for the pathway it is CURRENTLY assigned.

    python scripts/generate_pathway_notes.py --dry-run     # show what would be written, change nothing
    python scripts/generate_pathway_notes.py               # write into data/assets.json (backup made first)
    python scripts/generate_pathway_notes.py --sample 12   # print a random sample of the drafts

Rules
  * Writes pathwayNotes[<key of the assigned pathway>] (the note the portal shows as "Pathway Note").
  * NEVER overwrites a note that already exists (e.g. the palletising notes). Re-running only fills blanks.
  * Skips Out-of-Scope assets and assets with no pathway assigned.
  * Partners named in a note are only ever the ones already assigned to that asset (pathway.partners).
  * Style follows the Chifley register (data/assets-chif.json): how the item is isolated / removed (the defit),
    then how it is handled for that pathway. Wording is general practice, NOT site-verified method statements:
    these are drafts for the project team to review and edit.
"""
import argparse, datetime, json, random, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "assets.json"

KEY = {"Retain": "retain", "Reuse": "reuse", "Adaptive Reuse": "adaptiveReuse", "Refurbish": "refurbish",
       "Recycle": "recycle", "Dispose": "disposal", "Rehome": "rehome", "Remanufacture": "remanufacture",
       "Stewardship": "stewardship"}

# ── generic handling by pathway (used when a family has no specific wording for that pathway) ──────────
GENERIC = {
    "Retain": "Retain in place and protect from damage during strip-out. If removal becomes necessary, label and store for reinstallation.",
    "Reuse": "Remove with care, tag and stage in the designated area for reuse in the new fit-out. Confirm quantities and the receiving location with the client and design team.",
    "Rehome": "Clean, label and stage for collection by {P} for rehoming.",
    "Recycle": "Separate into material-specific bins and send to {P} for recycling.",
    "Dispose": "No suitable recovery route identified. Remove as general waste{vw}, separating any recyclable metal or e-waste first.",
    "Stewardship": "Palletise and return through the product stewardship scheme{via}.",
    "Remanufacture": "Remove intact, keep clean and dry, and send to {P} for remanufacture.",
}

# ── families: (name, title regex, defit sentence, {pathway: handling}) – first match wins ──────────────
FAMILIES = [
    ("exit sign", r"exit sign",
     "Isolate the sign from the emergency circuit, then remove it with its driver and battery.",
     {"Recycle": "Separate the battery and electronics for e-waste, the aluminium frame and steel brackets for metal recovery, and any glass or plastic panel into its own bin. Consolidate for collection{via}."}),

    ("light fitting", r"troffer|light panel|emergency led|downlight|pendant",
     "Fitting to be isolated and disconnected by a licensed electrician (lock-out/tag-out), then lowered out of the ceiling with its driver intact.",
     {"Retain": "Fittings identified for retention are removed with care, labelled and stored on site for reinstallation once the services consultant confirms scope.",
      "Recycle": "Place in the e-waste bin so metal, plastic and electronic components are separated and recovered{via}."}),

    ("electronics", r"smoke sensor|wap unit|network antenna|ewis|card reader|av interface|telephone|switches and outlets|gpo|power switcher|sensor",
     "Isolate the device from its power or data supply, then remove the unit with its backplate.",
     {"Retain": "Retain in place and protect during strip-out. If removal becomes necessary, label and store for reinstallation.",
      "Recycle": "Place in the e-waste bin for dedicated e-waste recycling{via}. Separate plastic housings, adhesives and screws into their own bins where practical.",
      "Dispose": "No suitable recovery route identified for this unit. Keep batteries and electronics out of general waste, and send the remainder{vw}."}),

    ("air diffuser / grille", r"diffuser|grille",
     "Mechanical contractor to disconnect from ductwork and flexible connections and remove from the ceiling, keeping any neck or plenum fittings with the unit.",
     {"Recycle": "Strip off any plastic, insulation or gaskets, then consolidate the metal units in the metal recycling bin for collection{via}.",
      "Dispose": "Units with no suitable recycling route are removed as general waste{vw}. Separate any clean metal first where practical."}),

    ("sprinkler", r"sprinkler",
     "Confirm the sprinkler is disconnected from the water supply before removal.",
     {}),

    ("resilient flooring", r"resilient flooring",
     "Lift sheet or tiles with a floor scraper, removing adhesive residue as far as practical, then roll or bag.",
     {"Dispose": "No suitable recycling route identified for this vinyl flooring. Send{vw}."}),

    ("joinery", r"joinery|benchtop|kitchenette|cabinetry|kitchen",
     "Disconnect plumbing and electrical services by licensed trades. Strip hardware (hinges, handles, slides) and deconstruct carcasses and benchtops into panels.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Recycle": "Send melamine-faced particleboard panels to {P}. Place metal hardware in the metal recycling bin."}),

    ("services metal (conduit)", r"conduit",
     "Isolate power and data, then remove conduit and fixings.",
     {"Recycle": "Place in the metal recycling bin for collection{via}."}),

    ("seating", r"chair|armchair|sofa|stool|seating|lounge",
     "Lift out by hand (no fixings), wipe down, and check the frame, mechanisms (gas lift, castors where fitted) and upholstery for damage.",
     {"Reuse": "Tag and group by model in the designated staging area for reuse in the new fit-out. Confirm the quantity required with the client and design team, and offer any surplus to {P} for rehoming.",
      "Rehome": "Allocate to {P} for rehoming. Clean, protect upholstery, stack safely and label by model so partners can collect in lots."}),

    ("tables / desks (loose)", r"^table|^desk - (semicircle|linear|corner|mobile|exec|custom)|^desk\b",
     "Unscrew or unclip tops from their bases (or lift out whole where free-standing), keep fixings with each table and protect edges and corners.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Rehome": "Allocate to {P} for rehoming. Clean, wrap corners, stack tops flat and bases together, and label by type for collection.",
      "Recycle": "Separate the particleboard top from the metal frame. Send the panels to {P} for particleboard recycling and the frames to the metal recycling bin."}),

    ("workstations", r"workstation",
     "Isolate power and data at the workstation (licensed electrician), then unbolt panels and desktops from the framing and keep fixings with the unit.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Reuse": "Keep motors, controls and cabling with each unit, wrap and label, and stage for reuse in the new fit-out. Confirm quantities and the receiving location with the client and design team.",
      "Recycle": "Consolidate the metal framing in the metal recycling bin, and send particleboard panels to {P}. Separate textile and plastic trims where practical."}),

    ("storage furniture", r"filing|cupboard|cabinet|pedestal|locker|shelving|shelf|tambour|storage",
     "Empty contents and remove keys. Take out drawers and shelves to reduce weight, secure doors, and move on a trolley.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Reuse": "Stage in the designated area for reuse in the new fit-out. Confirm quantities and the receiving location with the client and design team.",
      "Rehome": "Allocate to {P} for rehoming. Clean, tape drawers and doors shut, and label by type so they can be collected in lots.",
      "Recycle": "Strip out any non-metal parts and consolidate the steel in the metal recycling bin for collection{via}."}),

    ("appliances", r"refrigerator|freezer|appliance|water fountain|hot water|zip tap|sink",
     "Empty and clean, then have the unit disconnected from power and water by a licensed tradesperson. Secure any doors and remove loose parts.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Rehome": "Confirm the unit is in working order, then allocate to {P} for rehoming. Keep doors secured and label for collection.",
      "Recycle": "Where not suited to rehoming, send for metal and white-goods recycling{via}. Where fitted, refrigerants must be recovered by a licensed technician before any dismantling.",
      "Dispose": "No suitable recovery route identified. Keep any refrigerant, electronics and metal out of general waste, and send the remainder{vw}."}),

    ("glazing", r"glass|window pane|reception window",
     "Remove glazing with suction lifters, cutting silicone and releasing beads and fixings without shattering. Separate the glass from its framing.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Recycle": "Consolidate clean glass sheets, crate or palletise them, and send to {P}. Confirm the partner can accept laminated glass before collection."}),

    ("doors", r"door",
     "Leave door leaves hung where retained. If removal is needed, lift off hinges, keep hardware with each door and protect edges.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Recycle": "Strip hardware into the metal bin. Send the door leaf or frame to {P}. Confirm the core material first, as MDF cores are not suitable for recycling."}),

    ("insulation", r"insulation",
     "Once the plasterboard is de-skinned, expose and remove the insulation, keeping it dry and uncontaminated.",
     {"Remanufacture": "Bag in recycled or vacuum bags and send to {P} for reprocessing into new insulation product."}),

    ("framing", r"stud and track|partition wall",
     "Remove services from the wall first (GPO, data, switches and sensors to the e-waste bin), then de-skin the plasterboard from the framing.",
     {"Recycle": "Dismantle the steel stud and track and place it in the metal recycling bin for collection{via}."}),

    ("protection panel", r"protection panel",
     "Unfasten from its framing and handle with care, as panels may be heavy.",
     {"Dispose": "No suitable recycling route identified for this composite panel. Send{vw}, separating any metal fixings for recycling."}),

    ("blinds", r"blind",
     "Unclip from the head rail brackets, bundle by window and protect from bending.",
     {"Retain": "Retain in place and protect from damage during strip-out.",
      "Recycle": "Consolidate the aluminium in the metal recycling bin for collection{via}. Use any redundant blinds first to replace damaged perimeter blinds."}),

    ("skirting / jamb / ceiling grid", r"skirting|jamb|ceiling grid|ceiling channel",
     "Leave in place where retained and protect during strip-out.",
     {}),

    ("cabling", r"cabling",
     "Isolate and disconnect all cables from equipment before any removal.",
     {}),

    ("misc metal", r"whiteboard|partition|screen|archive|bin|safe",
     "Remove fixings and clear any contents, then lift out intact.",
     {"Reuse": "Stage in the designated area for reuse in the new fit-out. Confirm quantities and the receiving location with the client and design team.",
      "Rehome": "Allocate to {P} for rehoming. Keep clean and labelled for collection.",
      "Recycle": "Remove plastic, glass and other non-metal parts. Consolidate the metal in the recycling bin for collection{via}."}),
]

# ── hand-written notes where an existing workshop note / audit note changes the wording ───────────────────
# {title: {pathway: full note}}
OVERRIDES = {
    "Plasterboard Partition Wall": {"Retain": "Partition walls retained in place and protected during the works. Any plasterboard removed during strip-out is to be de-skinned from the framing, with services (GPO, data, switches, sensors) removed first and placed in the e-waste bin, and the sheeting placed in the plasterboard-only bin for recycling via pathway partner."},
    "Plasterboard Bulkhead": {"Retain": "Bulkheads retained in place and protected during the works. Any plasterboard removed during strip-out is to be separated from its framing, placed in the plasterboard-only bin and recycled via pathway partner."},
    "Power & Data Cabling": {"Retain": "Live cabling is retained in place. Cable removed during strip-out is to be isolated and disconnected from all equipment first, stripped of fittings, consolidated in the cable bin and recycled via pathway partner."},
    "Blinds - Venetian Window": {"Recycle": "Unclip from the head rail brackets and bundle by window. Use redundant venetian blinds first to replace any damaged perimeter blinds, and consolidate the remaining aluminium in the metal recycling bin for collection via pathway partner."},
    "Door - Glass Swing with Pull Handle": {"Retain": "Intent is to retain all glass swing doors in place. Protect glazing and hardware from damage during strip-out."},
    "Glass Partition - Reflective": {"Recycle": "Remove glazing with suction lifters, cutting silicone and releasing beads and fixings without shattering. The partition is not full length, so take care at the plasterboard junction above. Crate or palletise the glass and confirm that the pathway partner can accept laminated glass before collection, otherwise consider remanufacture through an alternative pathway partner."},
    "Paper Shredder": {"Reuse": "Disconnect from power and clear the bin of contents. Hold in the designated area until staff decide what to do with the item, then update the pathway accordingly."},
    "Printer": {"Reuse": "Disconnect from power and network and remove consumables. Hold in the designated area until staff decide what to do with the items, then update the pathway accordingly."},
    "Kitchen Appliances (various)": {"Rehome": "Separate appliances by type, empty and clean, and have each disconnected from power and water by a licensed tradesperson. Hold until staff decide what to do with these items, then allocate to the pathway partner for rehoming."},
    "Wall-mounted Screen": {"Rehome": "Disconnect from power and data and remove from the wall bracket, keeping the bracket and cables with the unit. Allocate to the pathway partner for rehoming, and look for additional charity partners local to the area to explore further rehoming options."},
    "Safe - Small": {"Reuse": "Confirm whether the safe is QPS property and whether it is being reused. Empty the contents and leave the door open, then move by a specialist. If not reused, rehome through a safe specialist."},
    "Safe - Large": {"Reuse": "Confirm whether the safe is QPS property and whether it is being reused. Empty the contents and leave the door open. Due to its weight, move only by a safe specialist. If not reused, rehome through a safe specialist."},
    "Library Shelf": {"Retain": "Intent is to retain. Hold in place and protect during strip-out. If it is not retained, the fallback is rehoming or recycling via pathway partner."},
    "Library Shelf - Low": {"Retain": "Intent is to retain. Hold in place and protect during strip-out. If it is not retained, the fallback is rehoming or recycling via pathway partner."},
    "ZIP Tap - 2-in-1": {"Retain": "Intent is to retain. Hold in place and protect during strip-out. If refurbishment is required, update the pathway accordingly, otherwise change to an end-of-life pathway (recycle or dispose)."},
    "Door - Solid Swing": {"Recycle": "Strip hardware into the metal bin and send the door leaf to the pathway partner. Confirm the core material first: if it is MDF, update the pathway to dispose."},
    # palletising wording mirrors the existing Carpet Tile - Grey note
    "Carpet Tile - Alternate": {"Stewardship": "Lift tiles by hand or with a scraper, stack face to face and palletise on a standard 1200x1200mm pallet up to 1.2m high. Check the pallet weight does not exceed the goods lift or tail lift limit before collection."},
    "Door - Glass with Timber Frame": {"Recycle": "Lift the door off its hinges and keep the hardware for the metal bin. Separate the glass from the timber frame by removing beads and silicone. Send the timber frame via pathway partner, and crate the glass for separate glass recycling."},
    "Desk Partition": {"Recycle": "Unclip or unscrew the partition screens from their desk mounts and keep fixings together. Separate any fabric or acoustic facing from the frame, and send the frames and panels via pathway partner for recycling."},
    "Workstation Partition": {"Recycle": "Isolate the power and services feeding the partition from the ceiling (licensed electrician). Unbolt the panels from the framing, separating the timber lower panels and textile upper panels from the metal frame. Send the metal framing to the metal recycling bin for collection via pathway partner, and the timber panels for particleboard recycling."},
    "Sink - Single with Mixer": {"Recycle": "Plumber to isolate and disconnect water and waste, then remove the sink and mixer. Separate the tap from the bowl and consolidate the metal in the metal recycling bin for collection via pathway partner."},
}


def fmt(text, partners):
    """Notes never name a partner: {P} -> "the pathway partner", {via} -> " via pathway partner".
    This keeps the notes valid when partner assignments change. {vw} (waste) names a licensed contractor only
    when no partner is assigned."""
    has = any(partners or [])
    P = "the pathway partner"
    via = " via pathway partner"
    vw = via if has else " via a licensed waste contractor"
    return text.replace("{P}", P).replace("{via}", via).replace("{vw}", vw)


def draft(asset):
    pw = (asset.get("pathway") or {}).get("suggested")
    partners = (asset.get("pathway") or {}).get("partners") or []
    title = asset["title"]
    if title in OVERRIDES and pw in OVERRIDES[title]:
        return "override", OVERRIDES[title][pw]
    low = title.lower()
    for name, rx, defit, by in FAMILIES:
        if re.search(rx, low):
            handling = by.get(pw) or GENERIC[pw]
            if pw == "Retain":      # staying in place: removal instructions would contradict the pathway
                return name, fmt(handling, partners)
            return name, fmt(f"{defit} {handling}", partners)
    return "generic", fmt(GENERIC[pw], partners)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="print N random drafts")
    args = ap.parse_args()

    raw = DATA.read_bytes()
    assets = json.loads(raw.decode("utf-8"))
    todo, skipped = [], {"out-of-scope": 0, "no pathway": 0, "already has a note": 0}
    for a in assets:
        if a.get("category") == "Out-of-Scope":
            skipped["out-of-scope"] += 1; continue
        pw = (a.get("pathway") or {}).get("suggested")
        if pw not in KEY:
            skipped["no pathway"] += 1; print(f"  - no pathway assigned, skipped: {a['title']}"); continue
        key = KEY[pw]
        if (a.get("pathwayNotes") or {}).get(key):
            skipped["already has a note"] += 1; continue
        fam, text = draft(a)
        todo.append((a, key, fam, text))

    fams = {}
    for _, _, fam, _ in todo:
        fams[fam] = fams.get(fam, 0) + 1
    print(f"\n{len(todo)} notes to write. Skipped: {skipped}")
    print("By family:", dict(sorted(fams.items(), key=lambda kv: -kv[1])))
    if fams.get("generic"):
        print("Generic (no family matched):", [a["title"] for a, _, f, _ in todo if f == "generic"])

    if args.sample:
        for a, key, fam, text in random.Random(7).sample(todo, min(args.sample, len(todo))):
            print(f"\n[{(a['pathway'] or {}).get('suggested')}] {a['title']}  ({fam})\n  {text}")

    if args.dry_run:
        print("\nDry run: nothing written."); return

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = backup_dir / f"assets_before_pathway_notes_{stamp}.json"
    backup.write_bytes(raw)
    for a, key, _, text in todo:
        a.setdefault("pathwayNotes", {})[key] = text
    # same formatting the editor uses (so the git diff only shows the notes)
    out = json.dumps(assets, indent=2, ensure_ascii=False)
    with open(DATA, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"\nWritten to {DATA.name}. Backup: {backup}")


if __name__ == "__main__":
    main()
