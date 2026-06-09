import pandas as pd, requests, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

df = pd.read_csv("bigcap_stocks.csv", dtype={"代码": str})
codes = df["代码"].tolist()
names = dict(zip(df["代码"], df["名称"]))
start = "2025-01-01"

def fetch(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,{start},,400,qfq"
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        key = prefix + code
        if "data" not in data or key not in data["data"]: return None
        kl = data["data"][key].get("qfqday") or data["data"][key].get("day")
        if not kl or len(kl) < 61: return None
        rows = []
        for row in kl:
            rows.append({"date": row[0], "close": float(row[2])})
        return rows
    except Exception as e:
        return None

print(f"Fetching {len(codes)} stocks...", flush=True)
results = {}
t0 = time.time()
with ThreadPoolExecutor(max_workers=30) as ex:
    fm = {ex.submit(fetch, c): c for c in codes}
    done = 0
    for f in as_completed(fm):
        c = fm[f]
        try: d = f.result()
        except: d = None
        if d: results[c] = d
        done += 1
        if done % 200 == 0: print(f"  {done}/{len(codes)} ok={len(results)} elapsed={time.time()-t0:.0f}s", flush=True)

print(f"Fetched {len(results)} stocks in {time.time()-t0:.0f}s", flush=True)

# Check turn_bull for each date
target_dates = ["2026-05-18","2026-05-19","2026-05-20","2026-05-21","2026-05-22"]

def check_turn_bull_for_date(rows, date):
    """Check turn_bull condition as if 'date' is today."""
    # Find index where date matches (must be exact)
    idx = None
    for i, r in enumerate(rows):
        if r["date"] == date:
            idx = i
            break
    if idx is None:
        return False
    # Use data up to and including this date
    closes = [r["close"] for r in rows[:idx+1]]
    n = len(closes)
    if n < 61:
        return False
    ma60 = [None]*59 + [sum(closes[i-59:i+1])/60 for i in range(59, n)]
    valid_start = next((i for i, v in enumerate(ma60) if v is not None), None)
    if valid_start is None or (n - valid_start) < 20:
        return False
    v_close = closes[valid_start:]
    v_ma60 = ma60[valid_start:]
    check_days = min(30, len(v_close) - 1)
    below_count = sum(1 for i in range(-check_days-1, -1) if v_close[i] < v_ma60[i])
    threshold = max(15, check_days * 2 // 3)
    if below_count < threshold:
        return False
    above = [v_close[i] > v_ma60[i] for i in range(len(v_close))]
    w = above[-(check_days+1):]
    tu = w[-1]; yu = w[-2] if len(w) >= 2 else False
    pb = any(w[:-1]); pby = any(w[:-2]) if len(w) > 2 else False
    return (tu and not pb) or (yu and tu and not pby)

# For each date, find all signals
for d in target_dates:
    sigs = []
    for code, rows in results.items():
        try:
            if check_turn_bull_for_date(rows, d):
                # Find close on that date
                for r in rows:
                    if r["date"] == d:
                        cl = r["close"]
                        break
                sigs.append(f"  {code} {names.get(code,'')} close={cl:.2f}")
        except:
            pass
    print(f"\n=== 转牛 {d} ({len(sigs)}只) ===")
    for s in sigs:
        print(s)
