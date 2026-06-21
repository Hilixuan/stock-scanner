"""历史信号存储与读取"""
import pickle
import requests
from pathlib import Path
from config import get_trading_date

HISTORY_FILE = Path("data_cache") / "signal_history.pkl"
BLOB_ID = None
BLOB_URL = None
GITHUB_FALLBACK = "https://raw.githubusercontent.com/Hilixuan/stock-scanner/history-data/history_data.json"
MAX_DAYS = 10
_BLOB_ID_FILE = Path("data_cache") / "blob_id.txt"


def _get_blob_url():
    global BLOB_ID, BLOB_URL
    if BLOB_URL is not None:
        return BLOB_URL
    if BLOB_ID is None:
        if _BLOB_ID_FILE.exists():
            BLOB_ID = _BLOB_ID_FILE.read_text(encoding="utf-8").strip()
        else:
            BLOB_ID = "019ee9a0-46d9-75cf-8cc6-ff718d46dfea"
    BLOB_URL = f"https://jsonblob.com/api/jsonBlob/{BLOB_ID}"
    return BLOB_URL


def _renew_blob():
    global BLOB_ID, BLOB_URL
    try:
        resp = requests.post("https://jsonblob.com/api/jsonBlob", json={}, timeout=15)
        if resp.status_code == 201:
            loc = resp.headers.get("Location", "")
            new_id = loc.replace("/api/jsonBlob/", "")
            if new_id:
                BLOB_ID = new_id
                BLOB_URL = f"https://jsonblob.com/api/jsonBlob/{BLOB_ID}"
                _BLOB_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
                _BLOB_ID_FILE.write_text(new_id, encoding="utf-8")
                return True
    except Exception:
        pass
    return False


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
    for url in (_get_blob_url(), GITHUB_FALLBACK):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            pass
    if _renew_blob():
        try:
            resp = requests.get(_get_blob_url(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data:
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
    """Push data to jsonblob.com (no auth needed). Auto-renew on expiry."""
    if not data:
        return
    try:
        url = _get_blob_url()
        resp = requests.put(url, json=data, timeout=15)
        if resp.status_code == 404:
            if _renew_blob():
                requests.put(_get_blob_url(), json=data, timeout=15)
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


def compute_and_save_today_missed(today_trend_codes, date=None):
    """Pre-compute trend-missed codes for all historical stocks and save under today's snapshot."""
    if date is None:
        from config import get_trading_date
        date = get_trading_date()
    history = _load()
    if not history:
        return set()
    all_codes = set()
    for day_data in history.values():
        for key in ("turn_bull", "trend"):
            for r in day_data.get(key, {}).get("stocks", []):
                all_codes.add(r.get("代码"))
    if not all_codes:
        return set()
    missed = get_today_ma5_above(all_codes, today_trend_codes)
    if date in history:
        history[date]["trend_missed"] = list(missed)
        _save(history)
    return missed
