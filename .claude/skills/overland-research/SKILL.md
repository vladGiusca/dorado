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

0. **Classify each target's size** and decide how many sub-regions to
   split it into. Judge by land area and geographic/cultural diversity,
   not just population — make a reasonable call yourself, don't ask the
   user to classify.

   | size | total POI target | example targets | sub-regions |
   |---|---|---|---|
   | small | ~100 | Georgia, Slovenia, Rwanda, Costa Rica, Jordan | 1 (no split — single subagent call) |
   | medium | 350-450 | Turkey, Vietnam, Kenya, Peru, Thailand | ~4-6 |
   | large | 550+ | Indonesia, USA, China, Russia, Brazil, India, Australia | ~7-12 |

   A named region spanning multiple countries (e.g. "Patagonia") is
   sized by the same judgment call, not defaulted to one bucket.

   For medium/large targets, divide the target into sensible geographic
   sub-regions that together cover the whole thing without much overlap
   (e.g. for Turkey: "Istanbul & Marmara", "Aegean Coast",
   "Mediterranean/Turquoise Coast", "Cappadocia & Central Anatolia",
   "Black Sea Coast", "Eastern Anatolia"). Divide the total POI target
   roughly evenly across sub-regions (round up) — this is a rough
   allocation, not a hard quota.

For **each** target, in parallel when there is more than one (issue all
the Agent tool calls for step 2 — across all sub-regions of all
targets — in a single message):

1. **Load context.** Run, once per top-level target (not per
   sub-region):
   ```
   python3 scripts/pois.py known "<target>"
   ```
   This returns the existing POIs (name/region_hint/country) already
   logged that match this target, so subagents don't re-research them.
   Give the same full list to every sub-region subagent spawned for
   this target.

2. **Spawn one subagent per sub-region** (or a single one for a small,
   unsplit target). Call the Agent tool with
   `subagent_type: "overland-scout"`. In the prompt, give it: the
   sub-region target string (e.g. "Cappadocia & Central Anatolia,
   Turkey", or just the country name if unsplit), the JSON known list
   from step 1, its target candidate count for this call, and a
   reminder that its final message must be a bare JSON array per its
   own instructions.

3. **Stage the output.** For each top-level target, concatenate the
   JSON arrays from all of its sub-region subagents into one combined
   array and write it to a scratchpad file (e.g.
   `<scratchpad>/pois-<slug-of-target>.json`).

4. **Append.** Run, once per top-level target, on the combined file:
   ```
   python3 scripts/pois.py append "<target>" <path-to-staged-json>
   ```
   This validates the candidates, generates `poi_id`s, sets
   `status=new` and `added_at`, merges sources into any existing-POI
   matches instead of duplicating (this also catches overlap between
   adjacent sub-regions), and appends to `data/pois.csv`. It prints a
   JSON summary: `{"added": [...], "merged": [...], "errors": [...]}`.

   If a subagent's output fails to parse as JSON, or `errors` in the
   summary is non-empty, fix the offending candidate(s) if it's an easy
   correction (e.g. re-run that sub-region's subagent once), otherwise
   report the error to the user rather than silently dropping rows.

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

After processing all targets, report to the user per target: the size
class and sub-region split used, how many POIs were added, how many
were merged into existing rows (with what was newly sourced), and any
errors. Point to `data/pois.csv` as the output file, and include the
Sheet URL from step 5 (or the sync error, if it failed).
