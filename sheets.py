"""
sheets.py — fetch and cache the checklist from Google Sheets.

The sheet is read-only from the bot's perspective.
Progress is stored in-memory (per team) and resets daily.
"""

import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from config import (
    GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON, SHEET_TAB_NAME,
    COL_TASK, COL_CATEGORY, COL_INSTRUCTIONS, COL_EQUIPMENT, COL_LOCATION
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

_tasks_cache: list[dict] = []


def _get_client() -> gspread.Client:
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def fetch_tasks(force_refresh: bool = False) -> list[dict]:
    """Return list of task dicts from the sheet. Cached after first fetch."""
    global _tasks_cache
    if _tasks_cache and not force_refresh:
        return _tasks_cache

    try:
        client = _get_client()
        sheet  = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_TAB_NAME)
        records = sheet.get_all_records()

        tasks = []
        for i, row in enumerate(records):
            task = {
                "id":           i,                              # 0-based index used as task ID
                "task":         str(row.get(COL_TASK, "")).strip(),
                "category":     str(row.get(COL_CATEGORY, "")).strip(),
                "instructions": str(row.get(COL_INSTRUCTIONS, "")).strip(),
                "equipment":    str(row.get(COL_EQUIPMENT, "")).strip(),
                "location":     str(row.get(COL_LOCATION, "")).strip(),
            }
            if task["task"]:            # skip blank rows
                tasks.append(task)

        _tasks_cache = tasks
        logger.info(f"Fetched {len(tasks)} tasks from Google Sheets.")
        return tasks

    except Exception as e:
        logger.error(f"Failed to fetch tasks from Google Sheets: {e}")
        return _tasks_cache     # return stale cache on error


def refresh_tasks() -> list[dict]:
    """Force a fresh pull from the sheet (called at daily reset)."""
    return fetch_tasks(force_refresh=True)
