"""历史信号存储与读取"""
import pickle
import requests
from pathlib import Path
from config import get_trading_date

HISTORY_FILE = Path("data_cache") / "signal_history.pkl"
BLOB_ID = "019ed59c-f449-75f9-9d95-93fe5329f4bd"
BLOB_URL = f"https://jsonblob.com/api/jsonBlob/{BLOB_ID}"
GITHUB_FALLBACK = "https://raw.githubusercontent.com/Hilixuan/stock-scanner/history-data/history_data.json"
MAX_DAYS = 10


def _clean(signals):
    return [{k: v for k, v in s.items() if k != "_detail_df"} for s in signals]


def _load():
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "rb") as f:
                data = pickle.load(f)
                if isinstance(data, dict) and data:
                    return data
    except Exception:
        pass
    for url in (BLOB_URL, GITHUB_FALLBACK):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and any(isinstance(v, dict) for v in data.values()):
                    return data
        except Exception:
            pass
    return {}


def _save(data):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(HISTORY_FILE)
    _sync(data)


def _sync(data):
    """Push data to jsonblob.com (no auth needed)."""
    if not data:
        return
    try:
        requests.put(BLOB_URL, json=data, timeout=15)
    except Exception:
        pass


def sync_remote():
    """Public API: push current history to jsonblob.com."""
    _sync(_load())


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


def get_resurgence(date, latest_date):
    """Return set of codes that are 死灰复燃 on the given date vs the latest date."""
    hist = get_snapshot(date)
    latest = get_snapshot(latest_date)
    if not hist or not latest:
        return set()

    latest_codes = set()
    for key in ("turn_bull", "trend"):
        for typ in ("stocks", "etfs"):
            for r in latest.get(key, {}).get(typ, []):
                latest_codes.add(r.get("代码"))

    candidates = set()
    for key in ("turn_bull", "trend"):
        for typ in ("stocks", "etfs"):
            for r in hist.get(key, {}).get(typ, []):
                code = r.get("代码")
                if code and code not in latest_codes:
                    candidates.add(code)

    if not candidates:
        return set()

    resurgence = set()
    for code in candidates:
        try:
            prefix = "sh" if code.startswith("6") else "sz"
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,60,qfq"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            days = data.get("data", {}).get(f"{prefix}{code}", {}).get("day", []) or \
                   data.get("data", {}).get(f"{prefix}{code}", {}).get("qfqday", [])
            if not days or len(days) < 50:
                continue
            closes = [float(d[2]) for d in days]
            if closes[-1] > sum(closes[-50:]) / 50:
                resurgence.add(code)
        except Exception:
            pass

    return resurgence


def get_today_ma5_above(codes, today_trend_codes):
    """Return codes where today close > MA5 but not in today's trend scan."""
    if not codes or today_trend_codes is None:
        return set()
    candidates = [c for c in codes if c not in today_trend_codes]
    if not candidates:
        return set()
    result = set()
    for code in candidates:
        try:
            prefix = "sh" if code.startswith("6") else "sz"
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,10,qfq"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            days = data.get("data", {}).get(f"{prefix}{code}", {}).get("day", []) or \
                   data.get("data", {}).get(f"{prefix}{code}", {}).get("qfqday", [])
            if not days or len(days) < 5:
                continue
            closes = [float(d[2]) for d in days[-5:]]
            ma5 = sum(closes) / 5
            if closes[-1] > ma5:
                result.add(code)
        except Exception:
            pass
    return result
