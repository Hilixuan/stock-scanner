"""
转牛选股法 — 独立扫描脚本
条件:
  1. 沪深主板股票，市值 ≥ 100亿
  2. 近30日收盘价 < MA60 (熊市运行)
  3. 今日收盘价 > MA60 且 > MA5 (转牛)
"""
import baostock as bs
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path

CACHE_DIR = Path("data_cache")
CACHE_DIR.mkdir(exist_ok=True)
MIN_MARKET_CAP = 100  # 亿
START_DATE = (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d")
TODAY = datetime.now().strftime("%Y-%m-%d")
CHUNK_SIZE = 500


def get_stock_list():
    lg = bs.login()
    if lg.error_code != "0":
        raise ConnectionError(lg.error_msg)
    try:
        rs = bs.query_all_stock(day=TODAY)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
    finally:
        bs.logout()
    df = pd.DataFrame(rows, columns=["code_prefix", "type_code", "名称"])
    df["代码"] = df["code_prefix"].str.replace(r"^(sh|sz)\.", "", regex=True)
    is_stock = df["code_prefix"].str.match(r"^(sh\.60|sz\.00)")
    df = df[is_stock].copy()
    non_st = ~df["名称"].str.contains("ST|退|PT", na=False)
    df = df[non_st]
    return df[["代码", "名称"]].reset_index(drop=True)


def get_market_cap(codes):
    results = {}
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        symbols = [f"sh{c}" if c.startswith("6") else f"sz{c}" for c in batch]
        url = "http://qt.gtimg.cn/q=" + ",".join(symbols)
        try:
            r = requests.get(url, timeout=10)
            for line in r.text.strip().split("\n"):
                parts = line.split("~")
                if len(parts) > 44:
                    c = parts[2][2:] if parts[2].startswith(("sh","sz")) else parts[2]
                    mcap_str = parts[44]
                    try:
                        results[c] = round(float(mcap_str), 2)
                    except (ValueError, TypeError):
                        pass
        except: pass
        time.sleep(0.1)
    return results


def check_turn_bull(df):
    if df is None or len(df) < 61:
        return False, None
    df = df.copy().sort_values("日期").reset_index(drop=True)
    df["MA60"] = df["收盘"].rolling(60).mean()
    df["MA5"] = df["收盘"].rolling(5).mean()
    valid = df["MA60"].notna()
    valid_range = df[valid].index
    if len(valid_range) < 20:
        return False, df
    check_days = min(30, len(valid_range) - 1)
    below = df["收盘"] < df["MA60"]
    below_count = int(below.iloc[-check_days-1:-1].sum())
    threshold = max(15, check_days * 2 // 3)
    if below_count < threshold:
        return False, df
    above = df["收盘"] > df["MA60"]
    window = above.iloc[-(check_days + 1):]
    today_above = window.iloc[-1]
    yesterday_above = window.iloc[-2] if len(window) >= 2 else False
    past_before_today = window.iloc[:-1]
    past_before_yesterday = window.iloc[:-2] if len(window) > 2 else pd.Series([], dtype=bool)
    if today_above and not past_before_today.any():
        return True, df
    if yesterday_above and today_above and not past_before_yesterday.any():
        return True, df
    return False, df


def _fetch_and_check_chunk(codes_chunk, names):
    lg = bs.login()
    if lg.error_code != "0":
        return []
    try:
        results = []
        for code in codes_chunk:
            name = names.get(code, "")
            prefix = "sh" if code.startswith("6") else "sz"
            bs_code = f"{prefix}.{code}"
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code, "date,open,high,low,close,preclose,volume,amount,pctChg",
                    start_date=START_DATE, end_date=TODAY,
                    frequency="d", adjustflag="2",
                )
                if rs.error_code != "0": continue
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows or len(rows) < 90: continue
                df = pd.DataFrame(rows, columns=[
                    "日期","开盘","最高","最低","收盘","昨收","成交量","成交额","涨跌幅"
                ])
                for col in ["开盘","最高","最低","收盘","昨收","成交量","成交额","涨跌幅"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            except Exception:
                continue

            is_signal, detail = check_turn_bull(df)
            if is_signal:
                latest = detail.iloc[-1]
                results.append({
                    "代码": code,
                    "名称": name,
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "MA5": round(float(latest["MA5"]), 2),
                    "MA60": round(float(latest["MA60"]), 2),
                })
        return results
    finally:
        bs.logout()


def main():
    print("=" * 60)
    print("转牛选股法")
    print(f"日期: {TODAY}")
    print("条件: 近30日收盘<MA60 ≥20天 → 今日收盘>MA60且>MA5 | 市值≥100亿")
    print("=" * 60)

    print("\n1/3 获取股票列表...")
    stocks = get_stock_list()
    print(f"  主板股票(非ST): {len(stocks)} 只")
    codes = stocks["代码"].tolist()
    names = dict(zip(stocks["代码"], stocks["名称"]))

    print("\n2/3 查询总市值...")
    mcap = get_market_cap(codes)
    big_caps = {k: v for k, v in mcap.items() if v >= MIN_MARKET_CAP}
    print(f"  市值≥{MIN_MARKET_CAP}亿: {len(big_caps)} 只")
    big_codes = list(big_caps.keys())

    print("\n3/3 获取行情 + 转牛筛选...")
    t0 = time.time()
    results = []
    for chunk_start in range(0, len(big_codes), CHUNK_SIZE):
        chunk = big_codes[chunk_start:chunk_start + CHUNK_SIZE]
        results.extend(_fetch_and_check_chunk(chunk, names))
        print(f"  进度: {min(chunk_start+CHUNK_SIZE, len(big_codes))}/{len(big_codes)}")
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.0f}s")

    if not results:
        print("\n未找到转牛股票")
        return

    df = pd.DataFrame(results)
    print(f"\n找到 {len(df)} 只转牛股票:\n")
    print(f"  {'#':>3} {'代码':>6} {'名称':>6} {'现价':>8} {'MA5':>8} {'MA60':>8} {'涨跌幅':>8}")
    print(f"  " + "-"*50)
    for i, r in df.iterrows():
        print(f"  {i+1:3d} {r['代码']:>6s} {r['名称']:>6s} {r['现价']:>8.2f} {r['MA5']:>8.2f} {r['MA60']:>8.2f} {r['涨跌幅']:>8s}")

    out = CACHE_DIR / "turn_bull_results.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
