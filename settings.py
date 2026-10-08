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


def require_settings(*names):
    missing = [name for name in names if not get_setting(name)]
    if missing:
        raise RuntimeError("Missing settings: " + ", ".join(missing))
