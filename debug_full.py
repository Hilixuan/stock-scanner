import pandas as pd, requests, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

df = pd.read_csv("bigcap_stocks.csv")
codes = df["代码"].tolist()
names = dict(zip(df["代码"], df["名称"]))
print(f"Read {len(codes)} codes from CSV", flush=True)

start = (datetime.now() - timedelta(days=912)).strftime("%Y-%m-%d")
print(f"Start date: {start}", flush=True)

def fetch(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,{start},,300,qfq"
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        key = prefix + code
        if "data" not in data or key not in data["data"]: return None
        kl = data["data"][key].get("qfqday") or data["data"][key].get("day")
        if not kl or len(kl) < 61: return None
        rows, prev_close = [], None
        for row in kl:
            ds = row[0]; cl = float(row[2]); op = float(row[1]); hi = float(row[3]); lo = float(row[4])
            vol = float(row[5]) if len(row) > 5 and row[5] else 0
            pct = 0.0
            if prev_close is not None and prev_close != 0:
                pct = round((cl - prev_close) / prev_close * 100, 2)
            prev_close = cl
            rows.append({"date": ds, "open": op, "high": hi, "low": lo, "close": cl, "volume": vol, "pct": pct})
        return rows
    except Exception as e:
        sys.stderr.write(f"ERR {code}: {type(e).__name__}: {e}\n")
        return None

print(f"Fetching {len(codes)} stocks...", flush=True)
results = {}
t0 = time.time()
with ThreadPoolExecutor(max_workers=30) as ex:
    fut_map = {ex.submit(fetch, c): c for c in codes}
    print(f"Submitted {len(fut_map)} futures", flush=True)
    done = 0
    for fut in as_completed(fut_map):
        c = fut_map[fut]
        try:
            d = fut.result()
            if d: results[c] = d
        except Exception as e:
            sys.stderr.write(f"FUT ERR {c}: {type(e).__name__}: {e}\n")
        done += 1
        if done % 200 == 0:
            elapsed = time.time() - t0
            print(f"  {done}/{len(codes)}  results={len(results)}  elapsed={elapsed:.0f}s", flush=True)

elapsed = time.time() - t0
print(f"Fetched {len(results)} stocks in {elapsed:.0f}s", flush=True)
