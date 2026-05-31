"""
Compare multiple strategies on NASDAQ 100 (513100).
Each strategy: buy/sell at close, full backtest 2024-05 ~ 2026-05.
"""

import requests
import pandas as pd
import pickle
from pathlib import Path

CODE = "513100"
SZ_CODE = "sh513100"
CACHE = Path(__file__).parent / "data_cache" / f"_{SZ_CODE}_sina.pkl"


def fetch_data():
    if CACHE.exists():
        with open(CACHE, "rb") as f:
            df = pickle.load(f)
        print(f"Loaded: {len(df)} rows")
        return df
    url = (f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={SZ_CODE}&scale=240&datalen=800")
    r = requests.get(url, timeout=15)
    data = r.json()
    df = pd.DataFrame(data)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns={"day": "date"}).sort_values("date").reset_index(drop=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(df, f)
    print(f"Fetched: {len(df)} rows, {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    return df


def run_strategy(df, buy_cond, sell_cond, name, start_i=20):
    """
    buy_cond(row, prev_row) -> True/False
    sell_cond(row, entry_price, entry_idx, df, i) -> True/False
    """
    trades = []
    in_pos = False
    entry_p, entry_d, entry_i = 0, "", 0

    for i in range(start_i, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1] if i > 0 else row

        if not in_pos:
            if buy_cond(row, prev):
                in_pos = True
                entry_p, entry_d, entry_i = row["close"], row["date"], i
        else:
            if sell_cond(row, entry_p, entry_i, df, i):
                exit_p = row["close"]
                pnl = round((exit_p - entry_p) / entry_p * 100, 2)
                label = f"+{pnl}%" if pnl >= 0 else f"{pnl}%"
                trades.append({
                    "entry_date": entry_d, "entry_price": entry_p,
                    "exit_date": row["date"], "exit_price": exit_p,
                    "pnl": pnl, "label": label,
                    "days": i - entry_i,
                })
                in_pos = False

    if in_pos:
        last = df.iloc[-1]
        pnl = round((last["close"] - entry_p) / entry_p * 100, 2)
        trades.append({
            "entry_date": entry_d, "entry_price": entry_p,
            "exit_date": last["date"] + " (持仓)", "exit_price": last["close"],
            "pnl": pnl, "label": f"+{pnl}%" if pnl >= 0 else f"{pnl}%",
            "days": len(df) - entry_i,
        })

    return trades


def calc_sharpe(trades):
    """Simple Sharpe-like ratio: avg_pnl / std_pnl (annualized approximation)"""
    if len(trades) < 2:
        return 0
    pnls = [t["pnl"] for t in trades]
    import statistics
    if statistics.stdev(pnls) == 0:
        return 0
    return round(statistics.mean(pnls) / statistics.stdev(pnls), 2)


def compound(trades, initial=100000):
    cash = initial
    for t in trades:
        cash *= (1 + t["pnl"] / 100)
    return round(cash, 2)


def max_drawdown(trades):
    """Max consecutive loss streak in percentage points"""
    if not trades:
        return 0
    peak = 0
    dd = 0
    cum = 100000
    for t in trades:
        cum *= (1 + t["pnl"] / 100)
        if cum > peak:
            peak = cum
        dd = min(dd, round((cum - peak) / peak * 100, 2))
    return dd


def run_all(df):
    results = []

    strategies = [
        # --- Rule A: 原始最优 MA5>MA10+close>MA5买, close<MA10卖 ---
        ("A: MA5>MA10+收>MA5买 / 收<MA10卖",
         lambda r, p: r["MA5"] > r["MA10"] and r["close"] > r["MA5"],
         lambda r, ep, ei, df, i: r["close"] < r["MA10"]),

        # --- Rule B: 放宽卖出 MA5>MA10+close>MA5买, close<MA20卖 ---
        ("B: MA5>MA10+收>MA5买 / 收<MA20卖",
         lambda r, p: r["MA5"] > r["MA10"] and r["close"] > r["MA5"],
         lambda r, ep, ei, df, i: r["close"] < r["MA20"]),

        # --- Rule C: 追涨买入(无close过滤), close<MA10卖 ---
        ("C: MA5>MA10买 / 收<MA10卖",
         lambda r, p: r["MA5"] > r["MA10"],
         lambda r, ep, ei, df, i: r["close"] < r["MA10"]),

        # --- Rule D: 趋势确认MA5>MA10>MA20, close<MA10卖 ---
        ("D: MA5>MA10>MA20买 / 收<MA10卖",
         lambda r, p: r["MA5"] > r["MA10"] > r["MA20"],
         lambda r, ep, ei, df, i: r["close"] < r["MA10"]),

        # --- Rule E: 三均线多排+收>MA5, 跌破MA10卖 ---
        ("E: MA5>MA10>MA20+收>MA5买 / 收<MA10卖",
         lambda r, p: r["MA5"] > r["MA10"] > r["MA20"] and r["close"] > r["MA5"],
         lambda r, ep, ei, df, i: r["close"] < r["MA10"]),

        # --- Rule F: ATR trailing stop ---
        ("F: MA5>MA10+收>MA5买 / ATR跟踪止盈",
         lambda r, p: r["MA5"] > r["MA10"] and r["close"] > r["MA5"],
         lambda r, ep, ei, df, i: r["close"] < df.loc[ei:i, "close"].max() * 0.93),

        # --- Rule G: MA5>MA10买, 跌破MA10或-5%止损卖 ---
        ("G: MA5>MA10买 / 收<MA10或-5%止损卖",
         lambda r, p: r["MA5"] > r["MA10"],
         lambda r, ep, ei, df, i: r["close"] < r["MA10"] or r["close"] < ep * 0.95),

        # --- Rule H: 双均线+放量 ---
        ("H: MA5>MA10+收>MA5+量>MA5量买 / 收<MA10卖",
         lambda r, p: r["MA5"] > r["MA10"] and r["close"] > r["MA5"] and r["volume"] > p["volume"],
         lambda r, ep, ei, df, i: r["close"] < r["MA10"]),

        # --- Rule I: 趋势跟踪 收>MA30买入, 收<MA30卖出 ---
        ("I: 收>MA30买 / 收<MA30卖",
         lambda r, p: r["close"] > r["MA30"],
         lambda r, ep, ei, df, i: r["close"] < r["MA30"]),

        # --- Rule J: 收>MA60买 / 收<MA60卖（长线持有） ---
        ("J: 收>MA60买 / 收<MA60卖",
         lambda r, p: r["close"] > r["MA60"],
         lambda r, ep, ei, df, i: r["close"] < r["MA60"]),
    ]

    print(f"\n{'策略':<35} {'交易':>4} {'胜率':>6} {'累计%':>8} {'资金':>10} {'最大回撤':>8} {'夏普':>6}")
    print("-" * 85)

    for name, buy_fn, sell_fn in strategies:
        start = 60 if "MA60" in name else (30 if "MA30" in name else 20)
        trades = run_strategy(df, buy_fn, sell_fn, name, start_i=start)

        if not trades:
            continue

        wins = sum(1 for t in trades if t["pnl"] > 0)
        total = sum(t["pnl"] for t in trades)
        final = compound(trades)
        dd = max_drawdown(trades)
        sharpe = calc_sharpe(trades)
        wr = round(wins / len(trades) * 100, 1)

        print(f"{name:<35} {len(trades):>4} {wr:>5}% {total:>+7.2f}% {final:>10.0f} {dd:>7.2f}% {sharpe:>6}")

    # Buy & hold
    cutoff = "2024-05-21"
    idx = df[df["date"] >= cutoff].index[0]
    bh_entry = df.loc[idx, "close"]
    bh_exit = df.iloc[-1]["close"]
    bh_ret = round((bh_exit - bh_entry) / bh_entry * 100, 2)
    print(f"\n{'买入持有':<35} {'1':>4} {'100%':>6} {bh_ret:>+7.2f}% {100000*(1+bh_ret/100):>10.0f}")

    return results


def main():
    df = fetch_data()

    # Calculate all MAs
    for n in [5, 10, 20, 30, 60]:
        df[f"MA{n}"] = df["close"].rolling(window=n).mean()

    print(f"\n513100 纳指ETF | {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    print(f"最新价: {df['close'].iloc[-1]}")
    print(f"\n===== 2024-05-21 ~ {df['date'].iloc[-1]} 多策略对比 =====")
    print(f"初始资金: 100,000")

    run_all(df)


if __name__ == "__main__":
    main()
