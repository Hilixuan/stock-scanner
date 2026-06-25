"""历史信号存储与读取"""
import pickle
import requests
import os
import base64
import json
from pathlib import Path
from config import get_trading_date

HISTORY_FILE = Path("data_cache") / "signal_history.pkl"
MAX_DAYS = 10
GITHUB_FALLBACK = "https://raw.githubusercontent.com/Hilixuan/stock-scanner/history-data/history_data.json"

_KNOWN_BLOBS = [
    "019ef990-0134-7fcb-a9d2-539aa7d4d092",
    "019ef990-3330-7a20-8a18-ec69ee37275a",
]

_BLOB_ID_FILE = Path("data_cache") / "blob_id.txt"
_ACTIVE_BLOB_ID = None
_GH_TOKEN = os.environ.get("GH_TOKEN", "")


def set_gh_token(token):
    global _GH_TOKEN
    _GH_TOKEN = token


def _sync_github(data):
    """Write history data to GitHub history-data branch using API."""
    if not _GH_TOKEN or not data:
        return
    try:
        url = "https://api.github.com/repos/Hilixuan/stock-scanner/contents/history_data.json"
        head_resp = requests.get(url + "?ref=history-data",
                                 headers={"Authorization": f"token {_GH_TOKEN}"}, timeout=10)
        sha = head_resp.json().get("sha", "") if head_resp.status_code == 200 else ""
        content = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8")
        body = {"message": "update history data", "content": content, "branch": "history-data"}
        if sha:
            body["sha"] = sha
        resp = requests.put(url, json=body,
                            headers={"Authorization": f"token {_GH_TOKEN}"}, timeout=15)
        return resp.status_code in (200, 201)
    except Exception:
        return False


def _blob_url(blob_id):
    return f"https://jsonblob.com/api/jsonBlob/{blob_id}"


def _read_blob(blob_id):
    try:
        resp = requests.get(_blob_url(blob_id), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data:
                return data
    except Exception:
        pass
    return None


def _write_blob(blob_id, data):
    try:
        resp = requests.put(_blob_url(blob_id), json=data, timeout=15)
        return resp.status_code == 200
    except Exception:
        return False


def _seed_blob(data):
    """Create a new blob with data and set it as the active blob."""
    new_id = _create_blob(data)
    if new_id:
        global _ACTIVE_BLOB_ID
        _ACTIVE_BLOB_ID = new_id


def _create_blob(data=None):
    try:
        body = {} if data is None else data
        resp = requests.post("https://jsonblob.com/api/jsonBlob", json=body, timeout=15)
        if resp.status_code == 201:
            loc = resp.headers.get("Location", "")
            new_id = loc.replace("/api/jsonBlob/", "")
            if new_id:
                _BLOB_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
                _BLOB_ID_FILE.write_text(new_id, encoding="utf-8")
                global _ACTIVE_BLOB_ID
                _ACTIVE_BLOB_ID = new_id
                return new_id
    except Exception:
        pass
    return None


def _active_blob():
    global _ACTIVE_BLOB_ID
    if _ACTIVE_BLOB_ID:
        return _ACTIVE_BLOB_ID
    if _BLOB_ID_FILE.exists():
        _ACTIVE_BLOB_ID = _BLOB_ID_FILE.read_text(encoding="utf-8").strip()
        return _ACTIVE_BLOB_ID
    return None


def _load():
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "rb") as f:
                data = pickle.load(f)
                if isinstance(data, dict) and data:
                    return data
    except Exception:
        pass
    blob_id = _active_blob()
    if blob_id:
        data = _read_blob(blob_id)
        if data:
            return data
    for bid in _KNOWN_BLOBS:
        if bid == blob_id:
            continue
        data = _read_blob(bid)
        if data:
            _BLOB_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _BLOB_ID_FILE.write_text(bid, encoding="utf-8")
            return data
    try:
        resp = requests.get(GITHUB_FALLBACK, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data:
                _seed_blob(data)
                return data
    except Exception:
        pass
    new_id = _create_blob()
    if new_id:
        data = _read_blob(new_id)
        if data:
            return data
    return {}


def _save(data):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(HISTORY_FILE)
    _sync(data)
    _sync_github(data)


def _sync(data):
    if not data:
        return
    blob_id = _active_blob()
    if blob_id and _write_blob(blob_id, data):
        return
    for bid in _KNOWN_BLOBS:
        if bid == blob_id:
            continue
        if _write_blob(bid, data):
            _BLOB_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _BLOB_ID_FILE.write_text(bid, encoding="utf-8")
            global _ACTIVE_BLOB_ID
            _ACTIVE_BLOB_ID = bid
            return
    new_id = _create_blob(data)
    if new_id:
        pass


def sync_remote():
    _sync(_load())


def save_turn_bull_snapshot(stocks, etfs):
    date = get_trading_date()
    history = _load()
    day = history.setdefault(date, {"turn_bull": {"stocks": [], "etfs": []}, "trend": {"stocks": [], "etfs": []}})
    day["turn_bull"]["stocks"] = _clean(stocks)
    day["turn_bull"]["etfs"] = _clean(etfs)
    _trim(history)
    _save(history)


def save_trend_snapshot(stocks, etfs):
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


def get_today_ma5_above(codes, today_trend_codes):
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


def _clean(signals):
    return [{k: v for k, v in s.items() if k != "_detail_df"} for s in signals]


def fetch_realtime_prices(codes):
    """Fetch real-time 现价 and 涨跌幅 for given stock/ETF codes via Tencent qt API."""
    if not codes:
        return {}
    grouped = {"sh": [], "sz": []}
    for c in codes:
        grouped["sh" if c.startswith("6") else "sz"].append(c)
    query = ",".join(f"{pre}{c}" for pre, cs in grouped.items() for c in cs)
    if not query:
        return {}
    try:
        resp = requests.get(f"http://qt.gtimg.cn/q={query}", timeout=5)
        result = {}
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parts = line.split("~")
                code = parts[2]
                cur = float(parts[3])
                pre_close = float(parts[4])
                chg = round((cur - pre_close) / pre_close * 100, 2) if pre_close else 0.0
                result[code] = {"现价": cur, "涨跌幅": f"{chg:+.2f}%"}
            except (IndexError, ValueError):
                continue
        return result
    except Exception:
        return {}