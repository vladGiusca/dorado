# dorado

Overlanding Research Agent — a Claude Code pipeline that researches
overlanding points of interest (POIs) and experiences for a country or
region, and accumulates them into `data/pois.csv` and a Google Sheet.

## How it works

Ask Claude Code to research a target and it will:

1. Spawn an `overland-scout` subagent per target, which researches the
   web (iOverlander, Horizons Unlimited, ADVrider, Wikivoyage, official
   park/border pages, overlanding blogs and forums) for POIs worth an
   overlander's detour — wild camps, technical passes, border crossings,
   hot springs, festivals, national parks, and the like.
2. Validate and append the results to `data/pois.csv` via
   `scripts/pois.py`, generating stable ids and skipping/merging
   anything already logged for that target.
3. Push new rows to a Google Sheet via `scripts/sync_sheet.py` — an
   all-countries `POIs` overview tab plus one tab per country, created
   automatically the first time a country appears.

Re-running a target is safe: existing POIs aren't duplicated, and any
edits you make by hand in the Sheet (e.g. setting `status` to
`reviewed`/`verified`) are never overwritten by a later sync.

## Usage

```
/overland-research Mongolia, Kazakhstan
/overland-research Patagonia
```

Targets are countries or named regions (which may span multiple
countries — the subagent assigns the right country to each POI it
finds). List several, comma-separated, to research them in parallel.

You can also run the pieces directly:

```
python3 scripts/pois.py known "Georgia"       # existing POIs for a target
python3 scripts/pois.py append "Georgia" x.json # validate + append candidates
python3 scripts/sync_sheet.py sync              # push new CSV rows to the Sheet
python3 scripts/sync_sheet.py url                # print the Sheet's URL
```

**Never hand-edit `data/pois.csv` directly** — always go through
`scripts/pois.py` so ids, validation, and dedup stay consistent. The
Google Sheet, on the other hand, is meant to be hand-edited (curation,
status changes); syncs only ever append new rows there.

## Schema

Each row in `data/pois.csv` (and the Sheet):

| field | set by | notes |
|---|---|---|
| `poi_id` | script | slug: `{iso2-country-code}-{kebab-case name}` |
| `country` | subagent | full country name |
| `region_hint` | subagent | sub-region/province/nearest town |
| `name` | subagent | common name of the POI/experience |
| `form` | subagent | `place`, `route`, `area`, `activity`, or `event` — shape on a map / what you do to visit it |
| `timing` | subagent | `anytime`, `seasonal`, `specific_dates`, or `weather_dependent` |
| `window` | subagent | blank if `timing` is `anytime`, else the season/date range/condition |
| `why` | subagent | 1-3 sentences on what makes it worth the detour |
| `time_needed` | subagent | free-text duration estimate |
| `sources` | subagent | `;`-separated URLs backing the entry |
| `confidence` | subagent | `Low`, `Medium`, or `High` |
| `status` | script | `new` on insert; `reviewed`/`verified`/`rejected` reserved for your own curation in the Sheet |
| `added_at` | script | ISO 8601 UTC timestamp |

## Project layout

```
.claude/agents/overland-scout.md       subagent: researches one target, returns JSON candidates
.claude/skills/overland-research/      skill: orchestrates research -> CSV -> Sheet
scripts/pois.py                        the only code that touches data/pois.csv
scripts/sync_sheet.py                  pushes new CSV rows to Google Sheets
data/pois.csv                          the POI database
```

## Google Sheets setup (one-time)

1. Install the Google API client libraries. On Arch:
   ```
   sudo pacman -S python-google-auth python-google-auth-oauthlib python-google-auth-httplib2 python-google-api-python-client
   ```
2. In the [Google Cloud Console](https://console.cloud.google.com/):
   create/select a project, then enable the **Google Sheets API**
   (APIs & Services → Library).
3. **APIs & Services → OAuth consent screen**: User type *External*,
   fill in the required fields, and add your own Google account under
   **Test users** (the app runs unverified, which is fine for personal
   use).
4. **APIs & Services → Credentials → Create Credentials → OAuth client
   ID**, application type **Desktop app**, then download the JSON.
5. Save it as `scripts/google/client_secret.json` (already gitignored).
6. Run `python3 scripts/sync_sheet.py sync` once — it opens a browser
   for consent and caches a token at `scripts/google/token.json`, so
   later syncs don't need the browser again.

See the docstring at the top of `scripts/sync_sheet.py` for details.
