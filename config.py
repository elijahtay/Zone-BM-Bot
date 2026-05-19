import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Google Sheets
GOOGLE_SHEET_ID        = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")  # JSON string of service account key

# Sheet tab name
SHEET_TAB_NAME = os.environ.get("SHEET_TAB_NAME", "Checklist")

# Column names in the sheet (adjust to match your actual headers)
COL_TASK        = os.environ.get("COL_TASK",         "Task")
COL_CATEGORY    = os.environ.get("COL_CATEGORY",     "Category")
COL_INSTRUCTIONS = os.environ.get("COL_INSTRUCTIONS","Instructions")
COL_EQUIPMENT   = os.environ.get("COL_EQUIPMENT",    "Equipment")
COL_LOCATION    = os.environ.get("COL_LOCATION",     "Location")   # where to get equipment

# Admin Telegram user IDs (comma-separated in env)
_admin_ids = os.environ.get("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = [int(x.strip()) for x in _admin_ids.split(",") if x.strip()]

# Daily reset time (Singapore time, UTC+8)
RESET_HOUR   = int(os.environ.get("RESET_HOUR",   "3"))   # 3 AM SGT
RESET_MINUTE = int(os.environ.get("RESET_MINUTE", "0"))

# Teams — can be overridden in env as comma-separated list
_teams = os.environ.get("TEAM_NAMES", "Team Alpha,Team Bravo,Team Charlie")
TEAM_NAMES = [t.strip() for t in _teams.split(",")]
