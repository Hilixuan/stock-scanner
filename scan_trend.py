"""
趋势选股扫描器
条件:
  1. 收盘 > MA60 (趋势确认)
  2. MA60 > MA60(5日前) (均线向上)
  3. 收盘 > MA20 (短线多头)
  4. 近5日涨幅 > 0 (短期动量)
  5. 近5日均量 ≥ MA60均量 * 0.8 (量能)
  6. 总市值 ≥ 50亿
  7. 非ST/退/PT
排名: MA60斜率 + 涨幅 + 量比 + 距离MA60幅度
"""
import pandas as pd
import numpy as np
import baostock as bs
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path

CACHE_DIR = Path("data_cache")
CACHE_DIR.mkdir(exist_ok=True)
MIN_MARKET_CAP_YI = 50
START_DATE = (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d")  # ~150日足够算MA60
TODAY = datetime.now().strftime("%Y-%m-%d")

# ── helpers ────────────────────────────────────────────────────────

def _disk_load(path):
    import pickle
    try:
        if path.exists():
            with open(path, "rb") as f:
                return pickle.load(f)
    except: pass
    return None

def _disk_save(data, path):
    import pickle
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    tmp.replace(path)

# ── stock list ─────────────────────────────────────────────────────

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

# ── market cap ─────────────────────────────────────────────────────

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
        except:
            pass
        time.sleep(0.1)
    return results

# ── batch fetch + screen ───────────────────────────────────────────

CHUNK_SIZE = 500

def _fetch_and_screen_chunk(codes_chunk, names, mcap):
    """Fetch kline for a chunk (single login), screen for trend, return matches."""
    lg = bs.login()
    if lg.error_code != "0":
        return []
    try:
        results = []
        for code in codes_chunk:
            prefix = "sh" if code.startswith("6") else "sz"
            bs_code = f"{prefix}.{code}"
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code, "date,open,high,low,close,preclose,volume,amount,pctChg",
                    start_date=START_DATE, end_date=TODAY,
                    frequency="d", adjustflag="2",
                )
                if rs.error_code != "0":
                    continue
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows or len(rows) < 61:
                    continue
                df = pd.DataFrame(rows, columns=[
                    "日期","开盘","最高","最低","收盘","昨收","成交量","成交额","涨跌幅"
                ])
                for col in ["开盘","最高","最低","收盘","昨收","成交量","成交额","涨跌幅"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            except Exception:
                continue

            close = df["收盘"].values
            volume = df["成交量"].values

            ma60 = pd.Series(close).rolling(60).mean().values
            ma20 = pd.Series(close).rolling(20).mean().values

            i = -1
            c = close[i]

            # 条件
            if c <= ma60[i]: continue
            if ma60[i] <= ma60[i-5]: continue
            if c <= ma20[i]: continue

            c5 = close[i-5]
            gain_5d = (c - c5) / c5 * 100
            if gain_5d <= 0: continue

            vol_5d_avg = volume[-5:].mean()
            vol_ma60 = pd.Series(volume).rolling(60).mean().values[i]
            if vol_ma60 <= 0 or vol_5d_avg < vol_ma60 * 0.8: continue

            # 评分
            ma60_slope = (ma60[i] - ma60[i-5]) / ma60[i-5]
            dist_ma60 = (c - ma60[i]) / ma60[i]
            vol_ratio = vol_5d_avg / vol_ma60 if vol_ma60 > 0 else 0
            pct_chg = df["涨跌幅"].values[i]
            score = ma60_slope * 100 + gain_5d + vol_ratio * 5 + dist_ma60 * 50

            results.append({
                "代码": code,
                "名称": names.get(code, ""),
                "总市值(亿)": mcap.get(code, 0),
                "收盘": c,
                "MA60": ma60[i],
                "MA20": ma20[i],
                "距MA60%": dist_ma60 * 100,
                "MA60斜率": ma60_slope,
                "5日涨幅%": gain_5d,
                "量比": vol_ratio,
                "涨跌幅": pct_chg,
                "score": score,
            })
        return results
    finally:
        bs.logout()


def screen_trend_stocks(codes, names, mcap):
    results = []
    total = len(codes)
    for chunk_start in range(0, total, CHUNK_SIZE):
        chunk = codes[chunk_start:chunk_start + CHUNK_SIZE]
        results.extend(_fetch_and_screen_chunk(chunk, names, mcap))
        print(f"  进度: {min(chunk_start+CHUNK_SIZE, total)}/{total}")
    return results


def main():
    print("=" * 60)
    print("趋势选股扫描器")
    print(f"日期: {TODAY}")
    print("条件: 收盘>MA60 | MA60向上 | 收盘>MA20 | 5日涨>0 | 量能≥0.8倍 | 市值≥50亿")
    print("=" * 60)

    print("\n1/3 获取股票列表...")
    stocks = get_stock_list()
    print(f"  主板股票(非ST): {len(stocks)} 只")

    codes = stocks["代码"].tolist()
    names = dict(zip(stocks["代码"], stocks["名称"]))

    print("\n2/3 查询总市值...")
    mcap = get_market_cap(codes)
    big_caps = {k: v for k, v in mcap.items() if v >= MIN_MARKET_CAP_YI}
    print(f"  市值≥{MIN_MARKET_CAP_YI}亿: {len(big_caps)} 只")

    big_codes = list(big_caps.keys())

    print("\n3/3 获取行情 + 趋势筛选 (可能需要几分钟)...")
    t0 = time.time()
    results = screen_trend_stocks(big_codes, names, big_caps)
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.0f}s")

    if not results:
        print("\n未找到符合条件的趋势股")
        return

    df = pd.DataFrame(results)
    df.sort_values("score", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    print(f"\n找到 {len(df)} 只趋势股 (按综合评分排序):\n")
    for i, row in df.iterrows():
        print(f"  #{i+1:2d} {row['代码']} {row['名称']:>6s} "
              f"市值{row['总市值(亿)']:>6.0f}亿  "
              f"收盘{row['收盘']:.2f}  "
              f"MA60{row['MA60']:.2f}  "
              f"距MA60{row['距MA60%']:.1f}%  "
              f"5日涨{row['5日涨幅%']:>+.1f}%  "
              f"量比{row['量比']:.2f}  "
              f"评分{row['score']:.0f}  "
              f"今日{row['涨跌幅']:>+.1f}%")

    # 保存结果
    out = CACHE_DIR / "trend_results.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
