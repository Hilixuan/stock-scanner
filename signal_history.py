"""历史信号存储与读取"""
import pickle
import requests
from pathlib import Path
from config import get_trading_date

HISTORY_FILE = Path("data_cache") / "signal_history.pkl"
MAX_DAYS = 10

import tempfile as _tempfile
_KNOWN_IDS_FILE = Path("data_cache") / "blob_ids.txt"
_KNOWN_IDS_FILE2 = Path(_tempfile.gettempdir()) / "stock_scanner_blob_ids.txt"
_HARDCODED_IDS = ["019f1890-1f8a-7ea0-8fab-b62bfb231999", "019f1890-2ca3-7c52-b99c-b978f6be0f6e"]


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


def _get_known_ids():
    ids = []
    for f in [_KNOWN_IDS_FILE, _KNOWN_IDS_FILE2]:
        try:
            if f.exists():
                raw = f.read_text(encoding="utf-8").strip()
                ids.extend([i.strip() for i in raw.split("\n") if i.strip()])
        except Exception:
            pass
    seen = set()
    result = []
    for bid in ids + _HARDCODED_IDS:
        if bid not in seen:
            seen.add(bid)
            result.append(bid)
    return result


def _save_known_ids(ids):
    payload = "\n".join(ids)
    for f in [_KNOWN_IDS_FILE, _KNOWN_IDS_FILE2]:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(payload, encoding="utf-8")
        except Exception:
            pass


def _save_blob(data):
    ids = _get_known_ids()
    wrote_any = False
    for bid in ids:
        if _write_blob(bid, data):
            wrote_any = True
    if not wrote_any:
        new_id = _create_blob(data)
        if new_id:
            ids.insert(0, new_id)
            _save_known_ids(ids)
    else:
        _save_known_ids(ids)


def _load():
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "rb") as f:
                d = pickle.load(f)
                if isinstance(d, dict) and d:
                    return d
    except Exception:
        pass
    for bid in _get_known_ids():
        d = _read_blob(bid)
        if d:
            _save_known_ids([bid] + [b for b in _get_known_ids() if b != bid])
            _write_blob(bid, d)  # renew expiry timer on every read
            return d
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
    try:
        _save_blob(data)
    except Exception:
        pass
    try:
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
    except Exception:
        pass


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
