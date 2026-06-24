"""Pre-compute all cache files locally, then commit to repo for cloud use."""
import sys, time, pickle
sys.path.insert(0, ".")
from pathlib import Path
from datetime import datetime, timedelta

# manual mock for fetch_one
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SECTOR_ETFS, OVERSEAS_ETFS, HISTORY_DAYS, get_trading_date
CACHE_DIR = Path("data_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_ALL_ETFS = SECTOR_ETFS + OVERSEAS_ETFS
start_date = (datetime.now() - timedelta(days=int(HISTORY_DAYS * 2.5))).strftime("%Y-%m-%d")
end_date = datetime.now().strftime("%Y-%m-%d")

def _save(data, name):
    p = CACHE_DIR / name
    tmp = p.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(p)
    print(f"  saved {name}: {p.stat().st_size/1024:.0f} KB")

t0 = time.time()

# ── 1. stock list ──
print("1/4 获取股票列表...")
import baostock as bs
lg = bs.login()
df = pd.DataFrame()
try:
    today = get_trading_date()
    rs = bs.query_all_stock(day=today)
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if rows:
        df = pd.DataFrame(rows, columns=["code_prefix", "type_code", "名称"])
        df["代码"] = df["code_prefix"].str.replace(r"^(sh|sz)\.", "", regex=True)
        not_st = ~df["名称"].str.contains("ST|退|PT", na=False)
        df = df[not_st]
        df = df[["代码", "名称"]].reset_index(drop=True)
finally:
    bs.logout()
if len(df) == 0:
    df = pd.read_csv("stock_list.csv")
    df = df[df["代码"].notna() & (df["代码"] != "")]
print(f"  {len(df)} 只股票")
_save(df, "stock_list.pkl")
stock_codes = df["代码"].tolist()

# ── 2. market cap ──
print("2/4 获取市值数据...")
def fetch_mcap_batch(batch):
    symbols = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch]
    url = "http://qt.gtimg.cn/q=" + ",".join(symbols)
    try:
        r = requests.get(url, timeout=10)
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
bsize = 50
batches = [stock_codes[i:i+bsize] for i in range(0, len(stock_codes), bsize)]
mcap = {}
with ThreadPoolExecutor(max_workers=20) as ex:
    for res in ex.map(fetch_mcap_batch, batches):
        mcap.update(res)
filtered = [c for c in stock_codes if mcap.get(c, 0) >= 100]
print(f"  {len(mcap)} / {len(filtered)} >= 100亿")
_save(mcap, "mcap_cache.pkl")

# ── 3. stock K-lines ──
print("3/4 获取个股日线行情...")
def tencent_fetch_one(code):
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,{start_date},,300,qfq"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        key = prefix + code
        if "data" not in data or key not in data["data"]: return None
        kline = data["data"][key].get("qfqday") or data["data"][key].get("day")
        if not kline or len(kline) < 30: return None
        rows, prev_close = [], None
        for row in kline:
            ds = row[0]
            if ds > end_date: break
            op, cl, hi, lo = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            vol = float(row[5]) if len(row) > 5 and row[5] else 0
            pct = 0.0
            if prev_close is not None and prev_close != 0:
                pct = round((cl - prev_close) / prev_close * 100, 2)
            prev_close = cl
            rows.append([ds, op, hi, lo, cl, vol, pct])
        df = pd.DataFrame(rows, columns=["日期","开盘","最高","最低","收盘","成交量","涨跌幅"])
        df["代码"] = code
        if code in mcap:
            df["总市值(亿)"] = mcap[code]
        return df
    except Exception:
        return None

target = filtered if filtered else stock_codes[:500]
results = {}
total = len(target)
with ThreadPoolExecutor(max_workers=30) as ex:
    fut_map = {ex.submit(tencent_fetch_one, c): c for c in target}
    done = 0
    for fut in as_completed(fut_map):
        c = fut_map[fut]
        try:
            df = fut.result()
            if df is not None:
                results[c] = df
        except Exception:
            pass
        done += 1
        if done % 100 == 0:
            print(f"  K-line 进度: {done}/{total}")
print(f"  {len(results)} 只股票有完整日线")
_save(results, "all_histories.pkl")

# ── 4. ETF K-lines ──
print("4/4 获取ETF日线行情...")
etf_raw = {}
etf_codes = [c for c, _ in _ALL_ETFS]
total_etf = len(etf_codes)
with ThreadPoolExecutor(max_workers=30) as ex:
    fut_map = {ex.submit(tencent_fetch_one, c): c for c in etf_codes}
    for fut in as_completed(fut_map):
        c = fut_map[fut]
        try:
            df = fut.result()
            if df is not None:
                etf_raw[c] = df
        except Exception:
            pass
etf_results = {}
for code, name in _ALL_ETFS:
    if code in etf_raw:
        etf_results[code] = {"name": name, "data": etf_raw[code]}
print(f"  {len(etf_results)} 只ETF")
_save(etf_results, "all_etfs.pkl")

print(f"\n完成，耗时 {time.time()-t0:.0f}s")
for f in ["stock_list.pkl","mcap_cache.pkl","all_histories.pkl","all_etfs.pkl"]:
    p = CACHE_DIR / f
    if p.exists():
        print(f"  {f}: {p.stat().st_size/1024:.0f} KB")
