#!/usr/bin/env python3
"""
Pushes new rows from data/pois.csv to a Google Sheet, without ever
touching rows already there — so a hand edit made in the Sheet (e.g.
changing status to reviewed/verified) survives future syncs. Uses OAuth
against your own Google account.

One-time setup:
    1. In https://console.cloud.google.com: create/select a project,
       then enable the "Google Sheets API" (APIs & Services > Library).
    2. APIs & Services > Credentials > Create Credentials > OAuth client
       ID > Application type "Desktop app". Download the JSON.
    3. Save it as scripts/google/client_secret.json (gitignored).
    4. Run this once interactively from a machine with a browser — it
       opens one for consent:
           python3 scripts/sync_sheet.py sync
       A token is cached at scripts/google/token.json afterward, so
       later syncs don't need the browser again.

Usage:
    sync_sheet.py sync   # create the sheet on first run, append any
                          # data/pois.csv rows not yet in it, print a
                          # summary + the sheet URL.
    sync_sheet.py url    # print the sheet URL without syncing.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pois  # noqa: E402  (scripts/pois.py - shared CSV schema/paths)

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_DIR = Path(__file__).resolve().parent / "google"
CLIENT_SECRET_PATH = GOOGLE_DIR / "client_secret.json"
TOKEN_PATH = GOOGLE_DIR / "token.json"
CONFIG_PATH = GOOGLE_DIR / "sheet_config.json"
SHEET_TITLE = "POIs"
SPREADSHEET_TITLE = "Dorado — Overlanding POIs"


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
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
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


def ensure_sheet(service):
    config = load_config()
    if config.get("spreadsheet_id"):
        return config["spreadsheet_id"], config["url"]

    spreadsheet = service.spreadsheets().create(
        body={
            "properties": {"title": SPREADSHEET_TITLE},
            "sheets": [{"properties": {"title": SHEET_TITLE}}],
        },
        fields="spreadsheetId,spreadsheetUrl",
    ).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]
    url = spreadsheet["spreadsheetUrl"]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{SHEET_TITLE}!A1",
        valueInputOption="RAW",
        body={"values": [pois.FIELDS]},
    ).execute()

    save_config({"spreadsheet_id": spreadsheet_id, "url": url})
    return spreadsheet_id, url


def existing_ids(service, spreadsheet_id):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"{SHEET_TITLE}!A2:A"
    ).execute()
    return {row[0] for row in result.get("values", []) if row}


def cmd_sync():
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)
    spreadsheet_id, url = ensure_sheet(service)

    rows = pois.read_rows()
    already = existing_ids(service, spreadsheet_id)
    new_rows = [r for r in rows if r["poi_id"] not in already]

    if new_rows:
        values = [[row.get(f, "") for f in pois.FIELDS] for row in new_rows]
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_TITLE}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

    print(json.dumps({
        "appended": len(new_rows),
        "poi_ids": [r["poi_id"] for r in new_rows],
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
