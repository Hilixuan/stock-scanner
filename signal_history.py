"""历史信号存储与读取"""
import json
import pickle
import os
import subprocess
import urllib.request
from pathlib import Path
from config import get_trading_date

HISTORY_FILE = Path("data_cache") / "signal_history.pkl"
HISTORY_JSON = Path("history_data.json")
REMOTE_RAW = "https://raw.githubusercontent.com/Hilixuan/stock-scanner/history-data/history_data.json"
MAX_DAYS = 10

GIT_REMOTE = "https://github.com/Hilixuan/stock-scanner.git"


def _clean(signals):
    return [{k: v for k, v in s.items() if k != "_detail_df"} for s in signals]


def _load():
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "rb") as f:
                return pickle.load(f)
    except Exception:
        pass
    try:
        if HISTORY_JSON.exists():
            with open(HISTORY_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    try:
        with urllib.request.urlopen(REMOTE_RAW, timeout=10) as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception:
        pass
    return {}


def _save(data):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(HISTORY_FILE)
    _write_json(data)


def _write_json(data):
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sync_to_git():
    """Push history_data.json to history-data branch (no deploy trigger)."""
    token = os.environ.get("GH_TOKEN")
    if not token:
        return
    try:
        _write_json(_load())
        subprocess.run(["git", "add", "history_data.json"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "update history [skip ci]"], check=True, capture_output=True)
        subprocess.run([
            "git", "push",
            f"https://{token}@github.com/Hilixuan/stock-scanner.git",
            "HEAD:history-data"
        ], check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "reset", "--soft", "HEAD~1"], check=True, capture_output=True)
        subprocess.run(["git", "reset", "history_data.json"], capture_output=True)
    except Exception:
        pass


def save_turn_bull_snapshot(stocks, etfs):
    """Save 转牛 scan results for today (merge with existing)."""
    date = get_trading_date()
    history = _load()
    day = history.setdefault(date, {"turn_bull": {"stocks": [], "etfs": []}, "trend": {"stocks": [], "etfs": []}})
    day["turn_bull"]["stocks"] = _clean(stocks)
    day["turn_bull"]["etfs"] = _clean(etfs)
    _trim(history)
    _save(history)


def save_trend_snapshot(stocks, etfs):
    """Save 趋势 scan results for today (merge with existing)."""
    date = get_trading_date()
    history = _load()
    day = history.setdefault(date, {"turn_bull": {"stocks": [], "etfs": []}, "trend": {"stocks": [], "etfs": []}})
    day["trend"]["stocks"] = _clean(stocks)
    day["trend"]["etfs"] = _clean(etfs)
    _trim(history)
    _save(history)


def _trim(history):
    dates = sorted(history.keys(), reverse=True)
    for d in dates[MAX_DAYS:]:
        del history[d]


def get_available_dates():
    return sorted(_load().keys(), reverse=True)


def get_snapshot(date):
    return _load().get(date)
