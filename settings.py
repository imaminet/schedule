import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
_local_path = BASE_DIR / "local_settings.json"
_local = json.loads(_local_path.read_text(encoding="utf-8")) if _local_path.exists() else {}


def get_setting(name, default=""):
    return str(os.environ.get(name, _local.get(name, default))).strip()


def today_jst():
    return datetime.now(JST).strftime("%Y-%m-%d")


def target_date_jst():
    value = os.environ.get("TARGET_DATE_JST", "").strip() or today_jst()
    if datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
        raise ValueError("TARGET_DATE_JST must be YYYY-MM-DD")
    return value


def now_jst():
    return datetime.now(JST).isoformat(timespec="seconds")


def require_settings(*names):
    missing = [name for name in names if not get_setting(name)]
    if missing:
        raise RuntimeError("Missing settings: " + ", ".join(missing))
