import baostock as bs
import pandas as pd
import streamlit as st
import requests
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from config import HISTORY_DAYS, get_trading_date

CACHE_DIR = Path("data_cache")
STOCK_LIST_FILE = CACHE_DIR / "stock_list.pkl"
ALL_HISTORIES_FILE = CACHE_DIR / "all_histories.pkl"
ALL_ETFS_FILE = CACHE_DIR / "all_etfs.pkl"

MIN_MARKET_CAP_YI = 100


def get_start_date():
    return (datetime.now() - timedelta(days=int(HISTORY_DAYS * 2.5))).strftime("%Y-%m-%d")


# ── disk cache helpers ────────────────────────────────────────────

def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _disk_load(path):
    try:
        if path.exists():
            with open(path, "rb") as f:
                return pickle.load(f)
    except Exception:
        pass
    return None


def _disk_save(data, path):
    _ensure_cache_dir()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(path)


def _cache_fresh(path, max_age_hours=12):
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age.total_seconds() < max_age_hours * 3600


# ── stock list (baostock — port 443, works fine) ──────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def get_stock_list():
    cached = _disk_load(STOCK_LIST_FILE)
    if cached is not None and _cache_fresh(STOCK_LIST_FILE):
        return cached

    def _parse_baostock():
        lg = bs.login()
        if lg.error_code != "0":
            return None
        try:
            today = get_trading_date()
            rs = bs.query_all_stock(day=today)
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["code_prefix", "type_code", "名称"])
            df["代码"] = df["code_prefix"].str.replace(r"^(sh|sz)\.", "", regex=True)
            is_stock = df["code_prefix"].str.match(r"^(sh\.60|sz\.00)")
            is_stock &= ~df["code_prefix"].str.match(r"^sh\.00")
            df = df[is_stock]
            non_st = ~df["名称"].str.contains("ST|退|PT", na=False)
            df = df[non_st]
            df = df[["代码", "名称"]].reset_index(drop=True)
            return df
        except Exception:
            return None
        finally:
            bs.logout()

    df = _parse_baostock()
    if df is not None and len(df) > 0:
        _disk_save(df, STOCK_LIST_FILE)
        return df

    # Fallback: static CSV
    csv_path = Path(__file__).parent / "stock_list.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        df = df[df["代码"].notna() & (df["代码"] != "")]
        _disk_save(df, STOCK_LIST_FILE)
        return df

    if cached is not None:
        return cached
    raise ConnectionError("无法获取股票列表（baostock 失败且无本地 CSV 缓存）")


# ── market cap (Tencent finance API) ──────────────────────────────

MCAP_CACHE_FILE = CACHE_DIR / "mcap_cache.pkl"

def _mcap_cache_fresh():
    if not MCAP_CACHE_FILE.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(MCAP_CACHE_FILE.stat().st_mtime)
    return age.total_seconds() < 86400

@st.cache_data(ttl=86400, show_spinner=False)
def get_market_cap(codes):
    cached = _disk_load(MCAP_CACHE_FILE)
    if cached is not None and _mcap_cache_fresh():
        return cached
    results = {}
    batch_size = 50
    def fetch_batch(batch):
        symbols = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch]
        url = "http://qt.gtimg.cn/q=" + ",".join(symbols)
        try:
            r = requests.get(url, timeout=8)
            out = {}
            for line in r.text.strip().split("\n"):
                parts = line.split("~")
                if len(parts) > 44:
                    c = parts[2][2:] if parts[2].startswith(("sh","sz")) else parts[2]
                    try:
                        out[c] = round(float(parts[44]), 2)
                    except (ValueError, TypeError):
                        pass
            return out
        except Exception:
            return {}
    batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    with ThreadPoolExecutor(max_workers=min(20, len(batches))) as ex:
        for res in ex.map(fetch_batch, batches):
            results.update(res)
    _disk_save(results, MCAP_CACHE_FILE)
    return results


# ── K-line data via Tencent finance API (parallel HTTP) ───────────

def _tencent_fetch_one(code, start_date, end_date):
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,{start_date},,300,qfq"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        key = prefix + code
        if "data" not in data or key not in data["data"]:
            return None
        kline = data["data"][key].get("qfqday") or data["data"][key].get("day")
        if not kline or len(kline) < 30:
            return None

        rows = []
        prev_close = None
        for row in kline:
            date_str = row[0]
            if date_str > end_date:
                break
            open_p = float(row[1]) if row[1] else 0
            close_p = float(row[2]) if row[2] else 0
            high_p = float(row[3]) if row[3] else 0
            low_p = float(row[4]) if row[4] else 0
            volume = float(row[5]) if len(row) > 5 and row[5] else 0

            pct_chg = 0.0
            if prev_close is not None and prev_close != 0:
                pct_chg = round((close_p - prev_close) / prev_close * 100, 2)
            prev_close = close_p

            rows.append([date_str, open_p, high_p, low_p, close_p, volume, pct_chg])

        df = pd.DataFrame(rows, columns=["日期", "开盘", "最高", "最低", "收盘", "成交量", "涨跌幅"])
        df["代码"] = code
        return df
    except Exception:
        return None


def _fetch_many(codes, start_date, end_date, progress_callback=None, max_workers=30, checkpoint_file=None, existing_results=None):
    """Fetch K-line for multiple stocks via parallel HTTP. Saves checkpoint every 100."""
    total = len(codes)
    if total == 0:
        return dict(existing_results or {})
    results = dict(existing_results or {})
    base = len(results)
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as executor:
        fut_map = {executor.submit(_tencent_fetch_one, code, start_date, end_date): code for code in codes}
        done = 0
        for future in as_completed(fut_map):
            code = fut_map[future]
            try:
                df = future.result()
                if df is not None:
                    results[code] = df
            except Exception:
                pass
            done += 1
            if checkpoint_file and done % 100 == 0:
                _disk_save(results, checkpoint_file)
            if progress_callback:
                progress_callback(base + done, base + total)
    if checkpoint_file:
        _disk_save(results, checkpoint_file)
    return results


# ── stock histories ───────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def _cached_fetch_single(code, start_date, end_date):
    return _tencent_fetch_one(code, start_date, end_date)


def fetch_single_history(code, start_date):
    end_date = datetime.now().strftime("%Y-%m-%d")
    return _cached_fetch_single(code, start_date, end_date)


def fetch_all_histories(codes, start_date, progress_callback=None):
    end_date = datetime.now().strftime("%Y-%m-%d")
    total = max(len(codes), 1)

    # Full cache (12h TTL)
    cached = _disk_load(ALL_HISTORIES_FILE)
    if cached is not None and _cache_fresh(ALL_HISTORIES_FILE):
        if progress_callback:
            progress_callback(len(cached), total)
        return cached

    mcap = get_market_cap(codes)
    filtered_codes = [c for c in codes if mcap.get(c, 0) >= MIN_MARKET_CAP_YI]
    if not filtered_codes:
        filtered_codes = codes[:500]
    total = max(len(filtered_codes), 1)

    # Partial checkpoint (10 min TTL) — resume support
    partial_file = CACHE_DIR / "histories_partial.pkl"
    partial = _disk_load(partial_file)
    if partial is not None and _cache_fresh(partial_file, max_age_hours=0.167):
        already = len(partial)
        remaining = [c for c in filtered_codes if c not in partial]
        if progress_callback and already > 0:
            progress_callback(already, total)
        results = _fetch_many(remaining, start_date, end_date,
                              lambda d, t: progress_callback(already + d, total) if progress_callback else None,
                              checkpoint_file=partial_file, existing_results=partial)
    else:
        results = _fetch_many(filtered_codes, start_date, end_date, progress_callback,
                              checkpoint_file=partial_file)

    for code, df in results.items():
        if code in mcap:
            df["总市值(亿)"] = mcap[code]

    _disk_save(results, ALL_HISTORIES_FILE)
    if partial_file.exists():
        partial_file.unlink()
    return results


# ── ETF histories ─────────────────────────────────────────────────

def fetch_etf_histories(start_date, etf_list=None):
    if etf_list is None:
        return {}
    end_date = datetime.now().strftime("%Y-%m-%d")

    cached = _disk_load(ALL_ETFS_FILE)
    if cached is not None and _cache_fresh(ALL_ETFS_FILE):
        return cached

    etf_codes = [code for code, _ in etf_list]
    raw = _fetch_many(etf_codes, start_date, end_date)

    results = {}
    for code, name in etf_list:
        if code in raw:
            results[code] = {"name": name, "data": raw[code]}

    _disk_save(results, ALL_ETFS_FILE)
    return results
