"""历史信号存储与读取"""
import pickle
import requests
from pathlib import Path
from config import get_trading_date

HISTORY_FILE = Path("data_cache") / "signal_history.pkl"
MAX_DAYS = 10

_BLOB_ID_FILE = Path("data_cache") / "blob_id.txt"
_BLOB_IDS = ["019ef990-0134-7fcb-a9d2-539aa7d4d092", "019ef990-3330-7a20-8a18-ec69ee37275a"]


def _blob_url(bid):
    return f"https://jsonblob.com/api/jsonBlob/{bid}"


def _read_blob(bid):
    try:
        r = requests.get(_blob_url(bid), timeout=8)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, dict) and d:
                return d
    except Exception:
        pass
    return None


def _write_blob(bid, data):
    try:
        r = requests.put(_blob_url(bid), json=data, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _create_blob(data):
    try:
        r = requests.post("https://jsonblob.com/api/jsonBlob", json=data, timeout=10)
        if r.status_code == 201:
            loc = r.headers.get("Location", "")
            new_id = loc.replace("/api/jsonBlob/", "")
            if new_id:
                return new_id
    except Exception:
        pass
    return None


def _save_blob(data):
    """Try known blobs, create new one if all dead."""
    for bid in _BLOB_IDS:
        if _write_blob(bid, data):
            _write_id(bid)
            return
    new_id = _create_blob(data)
    if new_id:
        _BLOB_IDS.insert(0, new_id)
        _write_id(new_id)


def _write_id(bid):
    try:
        _BLOB_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BLOB_ID_FILE.write_text(bid, encoding="utf-8")
    except Exception:
        pass


def _read_id():
    try:
        if _BLOB_ID_FILE.exists():
            return _BLOB_ID_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return None


def _load():
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "rb") as f:
                d = pickle.load(f)
                if isinstance(d, dict) and d:
                    return d
    except Exception:
        pass
    # try known blobs
    tried = set()
    bid = _read_id()
    if bid:
        tried.add(bid)
        d = _read_blob(bid)
        if d:
            return d
    for bid in _BLOB_IDS:
        if bid in tried:
            continue
        d = _read_blob(bid)
        if d:
            _write_id(bid)
            return d
    # try raw GitHub fallback
    try:
        r = requests.get("https://raw.githubusercontent.com/Hilixuan/stock-scanner/history-data/history_data.json", timeout=8)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, dict) and d:
                _save_blob(d)
                return d
    except Exception:
        pass
    return {}


def _save(data):
    import tempfile, os
    # save to jsonblob first (real persistence)
    _save_blob(data)
    # then local cache (ephemeral, just for speed)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=str(HISTORY_FILE.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(data, f)
        os.replace(tmp, HISTORY_FILE)
    except:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _clean(signals):
    return [{k: v for k, v in s.items() if k != "_detail_df"} for s in signals]


def _trim(history):
    dates = sorted(history.keys(), reverse=True)
    for d in dates[MAX_DAYS:]:
        del history[d]


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


def get_available_dates():
    return sorted(_load().keys(), reverse=True)


def get_snapshot(date):
    return _load().get(date)


def fetch_today_ma5(code):
    """Fetch today's close price and MA5 for a single stock. Returns (close, ma5) or None."""
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,10,qfq"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        days = data.get("data", {}).get(f"{prefix}{code}", {}).get("day", []) or \
               data.get("data", {}).get(f"{prefix}{code}", {}).get("qfqday", [])
        if not days or len(days) < 5:
            return None
        closes = [float(d[2]) for d in days[-5:]]
        ma5 = round(sum(closes) / 5, 2)
        return closes[-1], ma5
    except Exception:
        return None


def get_missed_codes(codes, today_trend_codes):
    """Return (sparked_set, {code: ma5_value}) for codes NOT in today's trend with close > MA5."""
    if not codes:
        return set(), {}
    candidates = [c for c in codes if today_trend_codes is None or c not in today_trend_codes]
    if not candidates:
        return set(), {}
    sparked = set()
    ma5_map = {}
    for code in candidates:
        result = fetch_today_ma5(code)
        if result:
            close_val, ma5_val = result
            ma5_map[code] = ma5_val
            if close_val > ma5_val:
                sparked.add(code)
    return sparked, ma5_map


def fetch_realtime_prices(codes):
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
