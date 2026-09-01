---
name: overland-research
description: Research overlanding points of interest/experiences for one or more countries or named regions and append them to data/pois.csv. Spawns one overland-scout subagent per target. Use when the user asks to research overlanding locations, POIs, or experiences for a country/region, or to grow the overlanding POI database.
---

# Overland Research

Orchestrates POI research: you (the main assistant) parse the requested
targets, spawn one `overland-scout` subagent per target, and use
`scripts/pois.py` to validate and append the results to `data/pois.csv`.
**Never hand-edit `data/pois.csv` directly** — all writes go through the
script so ids, validation, and dedup stay consistent.

## Input

The user's args are a comma-separated list of targets — each a country
or a named region (which may span multiple countries), e.g.:

```
/overland-research Mongolia, Kazakhstan
/overland-research Patagonia
```

If no targets are given, ask the user which country/region(s) to
research rather than guessing.

## Steps

For **each** target, in parallel when there is more than one (issue all
the Agent tool calls for step 2 in a single message):

1. **Load context.** Run:
   ```
   python3 scripts/pois.py known "<target>"
   ```
   This returns the existing POIs (name/region_hint/country) already
   logged that match this target, so the subagent doesn't re-research
   them.

2. **Spawn the subagent.** Call the Agent tool with
   `subagent_type: "overland-scout"`. In the prompt, give it the target
   string and the JSON from step 1 as the "known" list, and remind it
   its final message must be a bare JSON array per its own instructions.

3. **Stage the output.** Take the subagent's final JSON array and write
   it to a scratchpad file (e.g.
   `<scratchpad>/pois-<slug-of-target>.json`).

4. **Append.** Run:
   ```
   python3 scripts/pois.py append "<target>" <path-to-staged-json>
   ```
   This validates the candidates, generates `poi_id`s, sets
   `status=new` and `added_at`, merges sources into any existing-POI
   matches instead of duplicating, and appends to `data/pois.csv`. It
   prints a JSON summary: `{"added": [...], "merged": [...], "errors": [...]}`.

   If a subagent's output fails to parse as JSON, or `errors` in the
   summary is non-empty, fix the offending candidate(s) if it's an easy
   correction (e.g. re-run the subagent once), otherwise report the
   error to the user rather than silently dropping rows.

5. **Sync to Google Sheets.** Once all targets are processed, run:
   ```
   python3 scripts/sync_sheet.py sync
   ```
   This appends every `data/pois.csv` row not yet in the Sheet — it never
   touches rows already there, so any manual edits (e.g. a status change
   to `reviewed`/`verified`) made directly in the Sheet are preserved.
   It creates the Sheet on the very first run. Prints
   `{"appended": N, "poi_ids": [...], "sheet_url": "..."}`.

   If it fails with a missing-credentials error, this is one-time setup
   the user needs to do themselves (OAuth client + browser consent) —
   see the docstring at the top of `scripts/sync_sheet.py`. Tell the
   user what's missing and how to fix it rather than working around it;
   the CSV append in step 4 has already succeeded regardless, so no
   research is lost if the sync fails.

## Summary

After processing all targets, report to the user per target: how many
POIs were added, how many were merged into existing rows (with what was
newly sourced), and any errors. Point to `data/pois.csv` as the output
file, and include the Sheet URL from step 5 (or the sync error, if it
failed).
