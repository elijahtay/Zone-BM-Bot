# FM Checklist Bot 🤖

A Telegram bot for teams to access and track daily FM checklists sourced from Google Sheets.

---

## Features

- 📋 Browse tasks from Google Sheets with categories
- 📖 View instructions & equipment list per task
- 📍 See where to collect equipment
- ✅ Mark tasks done/undone per team independently
- 📊 Progress bar for each team
- 🔄 Automatic daily reset at 3 AM SGT
- 🔐 Admin commands for manual reset and cross-team summary

---

## Project Structure

```
fm-checklist-bot/
├── bot.py              # Entry point
├── config.py           # All config & env vars
├── sheets.py           # Google Sheets integration
├── store.py            # In-memory progress tracking
├── scheduler.py        # Daily reset scheduler
├── handlers/
│   ├── start.py        # /start + team selection
│   ├── checklist.py    # Browse, detail, toggle
│   └── admin.py        # /reset, /summary
├── requirements.txt
├── railway.toml
├── .env.example
└── .gitignore
```

---

## Google Sheets Setup

### 1. Create your sheet

Your sheet should have these column headers (names are configurable):

| Task | Category | Instructions | Equipment | Location |
|------|----------|--------------|-----------|----------|
| Clean AHU filters | ACMV | 1. Switch off AHU... | Filter brush, cloth | Level 3 Store Room |
| Check fire extinguisher | Safety | Inspect pressure gauge... | None | In-situ |

### 2. Create a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Download the JSON key file
6. **Share your Google Sheet** with the service account email (e.g. `bot@project.iam.gserviceaccount.com`) — Viewer access is enough

---

## Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow prompts
3. Copy the **Bot Token**
4. Set bot commands (optional but recommended):
   ```
   /setcommands → your bot → paste:
   start - Select your team
   checklist - View today's checklist
   progress - See your team's progress
   ```

---

## Local Development

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/fm-checklist-bot.git
cd fm-checklist-bot

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your values

# Run the bot
python bot.py
```

---

## Deploying to Railway

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/fm-checklist-bot.git
git push -u origin main
```

### 2. Deploy on Railway

1. Go to [railway.app](https://railway.app) and sign in
2. Click **New Project → Deploy from GitHub Repo**
3. Select your repository
4. Go to **Variables** tab and add all the variables from `.env.example`:

| Variable | Value |
|----------|-------|
| `BOT_TOKEN` | From BotFather |
| `GOOGLE_SHEET_ID` | From your Sheet URL |
| `GOOGLE_CREDENTIALS_JSON` | Full JSON key (one line) |
| `SHEET_TAB_NAME` | e.g. `Checklist` |
| `COL_TASK` | e.g. `Task` |
| `COL_CATEGORY` | e.g. `Category` |
| `COL_INSTRUCTIONS` | e.g. `Instructions` |
| `COL_EQUIPMENT` | e.g. `Equipment` |
| `COL_LOCATION` | e.g. `Location` |
| `TEAM_NAMES` | e.g. `Team Alpha,Team Bravo,Team Charlie` |
| `ADMIN_USER_IDS` | Your Telegram user ID |
| `RESET_HOUR` | `3` (3 AM SGT) |
| `RESET_MINUTE` | `0` |

5. Railway will auto-deploy. Check **Logs** tab to confirm `Bot is running...`

> **Tip:** To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot)

---

## Bot Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/start` | All | Select team, get started |
| `/checklist` | All | Browse today's task list |
| `/progress` | All | View your team's progress |
| `/reset` | Admin only | Manually reset all progress + refresh tasks |
| `/summary` | Admin only | View progress across all teams |

---

## Customising Team Names

Update `TEAM_NAMES` in your Railway environment variables:
```
TEAM_NAMES=Zone A,Zone B,Zone C
```
Changes take effect on next deployment or bot restart.

---

## Notes

- Progress is **in-memory** — it resets if the bot restarts. For persistent storage across restarts, a database (e.g. Railway PostgreSQL) can be added later.
- Tasks are **cached** from Google Sheets on first load and refreshed at each daily reset. Use `/reset` to force a refresh immediately.
