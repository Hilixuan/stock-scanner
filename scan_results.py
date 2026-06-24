import pandas as pd, requests, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

df = pd.read_csv("bigcap_stocks.csv", dtype={"代码": str})
codes = df["代码"].tolist()
names = dict(zip(df["代码"], df["名称"]))
start = (datetime.now() - timedelta(days=912)).strftime("%Y-%m-%d")

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
            ds = row[0]; cl = float(row[2])
            pct = 0.0
            if prev_close is not None and prev_close != 0:
                pct = round((cl - prev_close) / prev_close * 100, 2)
            prev_close = cl
            rows.append({"date": ds, "close": cl, "pct": pct, "open": float(row[1]), "volume": float(row[5]) if len(row) > 5 and row[5] else 0})
        return rows
    except Exception as e:
        sys.stderr.write(f"ERR {code}: {type(e).__name__}: {e}\n")
        return None

print(f"Fetching {len(codes)} stocks...", flush=True)
results = {}
t0 = time.time()
with ThreadPoolExecutor(max_workers=30) as ex:
    fut_map = {ex.submit(fetch, c): c for c in codes}
    done = 0
    for fut in as_completed(fut_map):
        c = fut_map[fut]
        try:
            d = fut.result()
            if d: results[c] = d
        except Exception as e:
            sys.stderr.write(f"FUT ERR {c}: {e}\n")
        done += 1
        if done % 200 == 0:
            print(f"  {done}/{len(codes)} ok={len(results)}", flush=True)
elapsed = time.time() - t0
print(f"Fetched {len(results)} stocks in {elapsed:.0f}s", flush=True)

tb_signals, tr_signals = [], []
for code, rows in results.items():
    closes = [r["close"] for r in rows]
    n = len(closes)
    name = names.get(code, "")
    if n >= 61:
        ma60 = [None]*59 + [sum(closes[i-59:i+1])/60 for i in range(59, n)]
        ma5 = [None]*4 + [sum(closes[i-4:i+1])/5 for i in range(4, n)]
        valid_start = next((i for i, v in enumerate(ma60) if v is not None), None)
        if valid_start is not None and (n - valid_start) >= 20:
            v_close = closes[valid_start:]
            v_ma60 = ma60[valid_start:]
            check_days = min(30, len(v_close) - 1)
            below_count = sum(1 for i in range(-check_days-1, -1) if v_close[i] < v_ma60[i])
            threshold = max(15, check_days * 2 // 3)
            if below_count >= threshold:
                above = [v_close[i] > v_ma60[i] for i in range(len(v_close))]
                window = above[-(check_days + 1):]
                today_up = window[-1]
                yesterday_up = window[-2] if len(window) >= 2 else False
                past_before_today = any(window[:-1])
                past_before_yesterday = any(window[:-2]) if len(window) > 2 else False
                if (today_up and not past_before_today) or (yesterday_up and today_up and not past_before_yesterday):
                    lc, lp = closes[-1], rows[-1]["pct"]
                    tb_signals.append(f"{code} {name} close={lc:.2f} chg={lp:+.2f}% MA5={ma5[-1]:.2f} MA60={ma60[-1]:.2f}")

    if n >= 30:
        ma5 = [None]*4 + [sum(closes[i-4:i+1])/5 for i in range(4, n)]
        ma15 = [None]*14 + [sum(closes[i-14:i+1])/15 for i in range(14, n)]
        valid_indices = [i for i, v in enumerate(ma15) if v is not None]
        if len(valid_indices) >= 15:
            last15 = valid_indices[-15:]
            c15 = [closes[i] for i in last15]
            m5_15 = [ma5[i] for i in last15]
            m15_15 = [ma15[i] for i in last15]
            above_ma5 = sum(1 for i in range(15) if c15[i] > m5_15[i])
            above_ma15 = sum(1 for i in range(15) if c15[i] > m15_15[i])
            if above_ma5 >= 12 and above_ma15 == 15:
                lc, lp = closes[-1], rows[-1]["pct"]
                tr_signals.append(f"{code} {name} close={lc:.2f} chg={lp:+.2f}% MA5={m5_15[-1]:.2f} MA15={m15_15[-1]:.2f}")

print(f"\n=== 转牛信号 ({len(tb_signals)} 只) ===")
for s in tb_signals: print(s)
print(f"\n=== 趋势信号 ({len(tr_signals)} 只) ===")
for s in tr_signals: print(s)
