#!/usr/bin/env python3
"""
Pushes new rows from data/pois.csv to a Google Sheet, without ever
touching rows already there — so a hand edit made in the Sheet (e.g.
changing status to reviewed/verified) survives future syncs. Uses OAuth
against your own Google account, via the device authorization flow (the
same mechanism `gcloud auth login --no-launch-browser` uses) — so
authorizing works even when this script runs somewhere other than the
machine with your browser (no localhost redirect required).

Layout: one "POIs" tab with every row (an all-countries overview), plus
one tab per country, auto-created the first time a country appears in
the CSV.

One-time setup:
    1. In https://console.cloud.google.com: create/select a project,
       then enable the "Google Sheets API" (APIs & Services > Library).
    2. APIs & Services > Credentials > Create Credentials > OAuth client
       ID > Application type "TVs and Limited Input devices" (this
       specific type is required for the device flow below — a
       "Desktop app" client will be rejected). Download the JSON.
    3. Save it as scripts/google/client_secret.json (gitignored).
    4. On the OAuth consent screen, add your own Google account under
       "Test users" (the app runs unverified).
    5. Run this once:
           python3 scripts/sync_sheet.py sync
       It prints a URL and a short code. Open the URL on any device
       (phone is fine), enter the code, and approve. A token is cached
       at scripts/google/token.json afterward, so later syncs don't
       need this step again.

Usage:
    sync_sheet.py sync   # create the spreadsheet on first run, ensure a
                          # tab exists per country, append any
                          # data/pois.csv rows not yet in their tab(s),
                          # print a summary + the sheet URL.
    sync_sheet.py url    # print the sheet URL without syncing.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pois  # noqa: E402  (scripts/pois.py - shared CSV schema/paths)

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_DIR = Path(__file__).resolve().parent / "google"
CLIENT_SECRET_PATH = GOOGLE_DIR / "client_secret.json"
TOKEN_PATH = GOOGLE_DIR / "token.json"
CONFIG_PATH = GOOGLE_DIR / "sheet_config.json"
OVERVIEW_TAB = "POIs"
SPREADSHEET_TITLE = "Dorado — Overlanding POIs"

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Characters Sheets tab titles can't contain, plus the 100-char limit.
_TAB_TITLE_BAD_CHARS = re.compile(r"[\[\]\*\/\\\?:]")


def _load_client_config():
    raw = json.loads(CLIENT_SECRET_PATH.read_text(encoding="utf-8"))
    section = raw.get("installed") or raw.get("web") or next(iter(raw.values()))
    return section["client_id"], section["client_secret"]


def run_device_flow():
    client_id, client_secret = _load_client_config()

    resp = requests.post(DEVICE_CODE_URL, data={
        "client_id": client_id,
        "scope": " ".join(SCOPES),
    })
    resp.raise_for_status()
    device = resp.json()

    print(f"Visit: {device['verification_url']}")
    print(f"Enter code: {device['user_code']}")

    interval = device.get("interval", 5)
    deadline = time.time() + device.get("expires_in", 1800)
    while time.time() < deadline:
        time.sleep(interval)
        token_resp = requests.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "device_code": device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        payload = token_resp.json()
        if token_resp.status_code == 200:
            return Credentials(
                token=payload["access_token"],
                refresh_token=payload.get("refresh_token"),
                token_uri=TOKEN_URL,
                client_id=client_id,
                client_secret=client_secret,
                scopes=SCOPES,
            )
        error = payload.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        print(f"Device authorization failed: {payload}", file=sys.stderr)
        sys.exit(1)

    print("Device authorization timed out waiting for approval.", file=sys.stderr)
    sys.exit(1)


def get_credentials():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_PATH.exists():
                print(
                    f"Missing {CLIENT_SECRET_PATH}. See the setup steps in "
                    "this script's docstring (python3 scripts/sync_sheet.py --help).",
                    file=sys.stderr,
                )
                sys.exit(1)
            creds = run_device_flow()
        GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config(config):
    GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def tab_title_for(country):
    title = _TAB_TITLE_BAD_CHARS.sub("-", country.strip())
    return title[:100] or "Unknown"


def quote_range(tab_title):
    return "'" + tab_title.replace("'", "''") + "'"


def ensure_spreadsheet(service):
    config = load_config()
    if config.get("spreadsheet_id"):
        return config["spreadsheet_id"], config["url"]

    spreadsheet = service.spreadsheets().create(
        body={
            "properties": {"title": SPREADSHEET_TITLE},
            "sheets": [{"properties": {"title": OVERVIEW_TAB}}],
        },
        fields="spreadsheetId,spreadsheetUrl",
    ).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]
    url = spreadsheet["spreadsheetUrl"]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{quote_range(OVERVIEW_TAB)}!A1",
        valueInputOption="RAW",
        body={"values": [pois.FIELDS]},
    ).execute()

    save_config({"spreadsheet_id": spreadsheet_id, "url": url})
    return spreadsheet_id, url


def existing_tab_titles(service, spreadsheet_id):
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties.title"
    ).execute()
    return {s["properties"]["title"] for s in meta.get("sheets", [])}


def ensure_country_tabs(service, spreadsheet_id, country_tab_titles):
    have = existing_tab_titles(service, spreadsheet_id)
    missing = [t for t in country_tab_titles if t not in have]
    if not missing:
        return

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [
            {"addSheet": {"properties": {"title": title}}} for title in missing
        ]},
    ).execute()

    for title in missing:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_range(title)}!A1",
            valueInputOption="RAW",
            body={"values": [pois.FIELDS]},
        ).execute()


def existing_ids(service, spreadsheet_id, tab_title):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"{quote_range(tab_title)}!A2:A"
    ).execute()
    return {row[0] for row in result.get("values", []) if row}


def append_new_rows(service, spreadsheet_id, tab_title, rows):
    already = existing_ids(service, spreadsheet_id, tab_title)
    new_rows = [r for r in rows if r["poi_id"] not in already]
    if new_rows:
        values = [[row.get(f, "") for f in pois.FIELDS] for row in new_rows]
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_range(tab_title)}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
    return [r["poi_id"] for r in new_rows]


def cmd_sync():
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)
    spreadsheet_id, url = ensure_spreadsheet(service)

    rows = pois.read_rows()

    rows_by_country = {}
    for row in rows:
        rows_by_country.setdefault(row["country"], []).append(row)

    country_tabs = {country: tab_title_for(country) for country in rows_by_country}
    ensure_country_tabs(service, spreadsheet_id, set(country_tabs.values()))

    overview_appended = append_new_rows(service, spreadsheet_id, OVERVIEW_TAB, rows)

    appended_by_country = {}
    for country, country_rows in rows_by_country.items():
        appended = append_new_rows(service, spreadsheet_id, country_tabs[country], country_rows)
        if appended:
            appended_by_country[country] = appended

    print(json.dumps({
        "overview_appended": len(overview_appended),
        "appended_by_country": {c: len(ids) for c, ids in appended_by_country.items()},
        "sheet_url": url,
    }, indent=2))


def cmd_url():
    config = load_config()
    if not config.get("url"):
        print("No sheet created yet - run `sync_sheet.py sync` first.", file=sys.stderr)
        sys.exit(1)
    print(config["url"])


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("sync", "url"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "sync":
        cmd_sync()
    else:
        cmd_url()


if __name__ == "__main__":
    main()
