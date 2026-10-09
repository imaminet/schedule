"""Freeze a target date using the original run creation time, never runner time."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from settings import JST


SCHEDULES = {
    "30 22 * * 0-4": ("morning", 7, 30),
    "0 8 * * 1-5": ("evening", 17, 0),
}


def select_context(event, schedule, mode, requested_date, created_at):
    anchor = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(JST)
    if event == "workflow_dispatch":
        if mode not in ("morning", "evening"):
            raise ValueError("Unknown mode")
        target = requested_date.strip() or anchor.date().isoformat()
        if datetime.strptime(target, "%Y-%m-%d").strftime("%Y-%m-%d") != target:
            raise ValueError("target_date must be YYYY-MM-DD")
        if target > anchor.date().isoformat():
            raise ValueError("Future target dates are not allowed")
        return mode, target
    if event != "schedule" or schedule not in SCHEDULES:
        raise ValueError(f"Unsupported event/schedule: {event} / {schedule}")
    mode, hour, minute = SCHEDULES[schedule]
    slot = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > anchor:
        slot -= timedelta(days=1)
    while slot.weekday() >= 5:
        slot -= timedelta(days=1)
    return mode, slot.date().isoformat()


def main():
    base = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{os.environ['GITHUB_REPOSITORY']}"
    response = requests.get(
        f"{base}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    response.raise_for_status()
    mode, target = select_context(
        os.environ["GITHUB_EVENT_NAME"], os.environ.get("SCHEDULE", ""),
        os.environ.get("REQUESTED_MODE", ""), os.environ.get("REQUESTED_DATE", ""),
        response.json()["created_at"],
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"mode={mode}\ndate={target}\n")
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        output.write(f"TARGET_DATE_JST={target}\n")
    print(f"Mode: {mode}; target date JST: {target}")


if __name__ == "__main__":
    main()
