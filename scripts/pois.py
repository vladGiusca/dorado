#!/usr/bin/env python3
"""
CSV read/write helper for data/pois.csv. This is the only code that
touches the CSV — schema validation, poi_id generation, and dedup/merge
logic all live here so the orchestrator (the overland-research skill)
never hand-edits the file.

Usage:
    pois.py known "<target>"
        Print existing POIs (name/region_hint/country) whose country or
        region_hint matches <target>, as a JSON array. Use this to give
        an overland-scout subagent context on what's already logged.

    pois.py append "<target>" <candidates.json>
        Read a JSON array of candidate POIs (subagent output) and append
        new ones to data/pois.csv, merging sources into existing rows on
        an exact (country, name-slug) match instead of duplicating.
        Prints a JSON summary: {"added": [...], "merged": [...], "errors": [...]}.
"""
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "pois.csv"

FIELDS = [
    "poi_id", "country", "region_hint", "name", "form", "timing", "window",
    "why", "time_needed", "sources", "confidence", "status", "added_at",
]

FORM_VALUES = {"place", "route", "area", "activity", "event"}
TIMING_VALUES = {"anytime", "seasonal", "specific_dates", "weather_dependent"}
CONFIDENCE_VALUES = {"Low", "Medium", "High"}

REQUIRED_CANDIDATE_FIELDS = [
    "country", "region_hint", "name", "form", "timing", "window", "why",
    "time_needed", "sources", "confidence",
]

# Common overlanding-relevant countries. Anything missing falls back to a
# derived pseudo-code rather than failing the whole append.
COUNTRY_TO_ISO2 = {
    "afghanistan": "af", "albania": "al", "algeria": "dz", "angola": "ao",
    "argentina": "ar", "armenia": "am", "australia": "au", "austria": "at",
    "azerbaijan": "az", "bangladesh": "bd", "belarus": "by", "belgium": "be",
    "belize": "bz", "benin": "bj", "bhutan": "bt", "bolivia": "bo",
    "bosnia and herzegovina": "ba", "botswana": "bw", "brazil": "br",
    "bulgaria": "bg", "burkina faso": "bf", "burundi": "bi", "cambodia": "kh",
    "cameroon": "cm", "canada": "ca", "chad": "td", "chile": "cl",
    "china": "cn", "colombia": "co", "congo": "cg",
    "democratic republic of the congo": "cd", "costa rica": "cr",
    "croatia": "hr", "cuba": "cu", "cyprus": "cy", "czechia": "cz",
    "czech republic": "cz", "denmark": "dk", "djibouti": "dj",
    "dominican republic": "do", "ecuador": "ec", "egypt": "eg",
    "el salvador": "sv", "estonia": "ee", "eswatini": "sz", "ethiopia": "et",
    "fiji": "fj", "finland": "fi", "france": "fr", "gabon": "ga",
    "georgia": "ge", "germany": "de", "ghana": "gh", "greece": "gr",
    "greenland": "gl", "guatemala": "gt", "guinea": "gn",
    "guyana": "gy", "honduras": "hn", "hungary": "hu", "iceland": "is",
    "india": "in", "indonesia": "id", "iran": "ir", "iraq": "iq",
    "ireland": "ie", "israel": "il", "italy": "it", "ivory coast": "ci",
    "cote d'ivoire": "ci", "jamaica": "jm", "japan": "jp", "jordan": "jo",
    "kazakhstan": "kz", "kenya": "ke", "kosovo": "xk", "kuwait": "kw",
    "kyrgyzstan": "kg", "laos": "la", "latvia": "lv", "lebanon": "lb",
    "lesotho": "ls", "libya": "ly", "lithuania": "lt", "madagascar": "mg",
    "malawi": "mw", "malaysia": "my", "mali": "ml", "mauritania": "mr",
    "mexico": "mx", "moldova": "md", "mongolia": "mn", "montenegro": "me",
    "morocco": "ma", "mozambique": "mz", "myanmar": "mm", "namibia": "na",
    "nepal": "np", "netherlands": "nl", "new zealand": "nz",
    "nicaragua": "ni", "niger": "ne", "nigeria": "ng",
    "north macedonia": "mk", "norway": "no", "oman": "om",
    "pakistan": "pk", "palestine": "ps", "panama": "pa",
    "papua new guinea": "pg", "paraguay": "py", "peru": "pe",
    "philippines": "ph", "poland": "pl", "portugal": "pt", "qatar": "qa",
    "romania": "ro", "russia": "ru", "rwanda": "rw",
    "saudi arabia": "sa", "senegal": "sn", "serbia": "rs",
    "sierra leone": "sl", "slovakia": "sk", "slovenia": "si",
    "somalia": "so", "south africa": "za", "south korea": "kr",
    "south sudan": "ss", "spain": "es", "sri lanka": "lk", "sudan": "sd",
    "suriname": "sr", "sweden": "se", "switzerland": "ch", "syria": "sy",
    "taiwan": "tw", "tajikistan": "tj", "tanzania": "tz", "thailand": "th",
    "timor-leste": "tl", "togo": "tg", "tunisia": "tn", "turkey": "tr",
    "turkmenistan": "tm", "uganda": "ug", "ukraine": "ua",
    "united arab emirates": "ae", "united kingdom": "gb",
    "united states": "us", "united states of america": "us",
    "uruguay": "uy", "uzbekistan": "uz", "vanuatu": "vu",
    "venezuela": "ve", "vietnam": "vn", "western sahara": "eh",
    "yemen": "ye", "zambia": "zm", "zimbabwe": "zw",
}


def slugify(text):
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def country_to_iso2(country):
    key = country.strip().lower()
    if key in COUNTRY_TO_ISO2:
        return COUNTRY_TO_ISO2[key]
    fallback = re.sub(r"[^a-z]", "", key)[:2]
    return fallback or "xx"


def read_rows():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def cmd_known(target):
    target_l = target.strip().lower()
    rows = read_rows()
    matches = []
    for row in rows:
        country_l = row.get("country", "").lower()
        region_l = row.get("region_hint", "").lower()
        if (
            target_l in country_l or country_l in target_l
            or target_l in region_l
        ):
            matches.append({
                "name": row.get("name", ""),
                "region_hint": row.get("region_hint", ""),
                "country": row.get("country", ""),
            })
    print(json.dumps(matches, indent=2))


def validate_candidate(candidate, errors, index):
    missing = [f for f in REQUIRED_CANDIDATE_FIELDS if not candidate.get(f) and f != "window"]
    if missing:
        errors.append(f"candidate[{index}] missing required field(s): {', '.join(missing)}")
        return False
    if candidate["form"] not in FORM_VALUES:
        errors.append(f"candidate[{index}] invalid form: {candidate['form']!r}")
        return False
    if candidate["timing"] not in TIMING_VALUES:
        errors.append(f"candidate[{index}] invalid timing: {candidate['timing']!r}")
        return False
    if candidate["confidence"] not in CONFIDENCE_VALUES:
        errors.append(f"candidate[{index}] invalid confidence: {candidate['confidence']!r}")
        return False
    return True


def merge_sources(existing_sources, new_sources):
    existing = [s.strip() for s in existing_sources.split(";") if s.strip()]
    seen = set(existing)
    for s in (s.strip() for s in new_sources.split(";")):
        if s and s not in seen:
            existing.append(s)
            seen.add(s)
    return ";".join(existing)


def cmd_append(target, candidates_path):
    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)

    rows = read_rows()
    existing_by_key = {}
    existing_ids = set()
    for row in rows:
        key = (row["country"].strip().lower(), slugify(row["name"]))
        existing_by_key[key] = row
        existing_ids.add(row["poi_id"])

    added, merged, errors = [], [], []

    for i, candidate in enumerate(candidates):
        if not validate_candidate(candidate, errors, i):
            continue

        timing = candidate["timing"]
        window = candidate.get("window", "") or ""
        window = "" if timing == "anytime" else window
        if timing != "anytime" and not window:
            errors.append(
                f"candidate[{i}] ({candidate['name']!r}) warning: timing={timing!r} but window is blank"
            )

        key = (candidate["country"].strip().lower(), slugify(candidate["name"]))
        if key in existing_by_key:
            existing_row = existing_by_key[key]
            existing_row["sources"] = merge_sources(existing_row["sources"], candidate["sources"])
            merged.append(existing_row["poi_id"])
            continue

        iso2 = country_to_iso2(candidate["country"])
        base_id = f"{iso2}-{slugify(candidate['name'])}"
        poi_id = base_id
        suffix = 2
        while poi_id in existing_ids:
            poi_id = f"{base_id}-{suffix}"
            suffix += 1
        existing_ids.add(poi_id)

        row = {
            "poi_id": poi_id,
            "country": candidate["country"],
            "region_hint": candidate["region_hint"],
            "name": candidate["name"],
            "form": candidate["form"],
            "timing": timing,
            "window": window,
            "why": candidate["why"],
            "time_needed": candidate["time_needed"],
            "sources": candidate["sources"],
            "confidence": candidate["confidence"],
            "status": "new",
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        rows.append(row)
        existing_by_key[key] = row
        added.append(poi_id)

    write_rows(rows)
    print(json.dumps({"target": target, "added": added, "merged": merged, "errors": errors}, indent=2))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "known":
        if len(sys.argv) != 3:
            print("usage: pois.py known \"<target>\"", file=sys.stderr)
            sys.exit(1)
        cmd_known(sys.argv[2])
    elif cmd == "append":
        if len(sys.argv) != 4:
            print("usage: pois.py append \"<target>\" <candidates.json>", file=sys.stderr)
            sys.exit(1)
        cmd_append(sys.argv[2], sys.argv[3])
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
