"""
store.py — per-team progress tracking (in-memory, resets daily).

Structure:
    _progress = {
        "Team Alpha": {0: True, 3: True, ...},   # task_id -> done
        "Team Bravo": {},
        ...
    }

    _user_teams = {
        telegram_user_id (int): "Team Alpha",
        ...
    }
"""

import logging
from config import TEAM_NAMES

logger = logging.getLogger(__name__)

# {team_name: {task_id: bool}}
_progress: dict[str, dict[int, bool]] = {team: {} for team in TEAM_NAMES}

# {user_id: team_name}
_user_teams: dict[int, str] = {}


# ── Team assignment ────────────────────────────────────────────────────────────

def set_user_team(user_id: int, team: str) -> None:
    _user_teams[user_id] = team
    logger.info(f"User {user_id} assigned to {team}")


def get_user_team(user_id: int) -> str | None:
    return _user_teams.get(user_id)


def get_all_teams() -> list[str]:
    return list(_progress.keys())


# ── Progress ───────────────────────────────────────────────────────────────────

def is_done(team: str, task_id: int) -> bool:
    return _progress.get(team, {}).get(task_id, False)


def toggle_task(team: str, task_id: int) -> bool:
    """Toggle a task's completion state. Returns the new state."""
    if team not in _progress:
        _progress[team] = {}
    current = _progress[team].get(task_id, False)
    _progress[team][task_id] = not current
    return not current


def get_team_progress(team: str, total: int) -> dict:
    done = sum(1 for v in _progress.get(team, {}).values() if v)
    return {"done": done, "total": total, "pct": int(done / total * 100) if total else 0}


def get_all_progress(total: int) -> dict[str, dict]:
    return {team: get_team_progress(team, total) for team in _progress}


# ── Reset ──────────────────────────────────────────────────────────────────────

def reset_all_progress() -> None:
    for team in _progress:
        _progress[team] = {}
    logger.info("All team progress has been reset.")


def reset_team_progress(team: str) -> None:
    if team in _progress:
        _progress[team] = {}
    logger.info(f"Progress reset for {team}.")
