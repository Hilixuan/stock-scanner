import requests
import pandas as pd
import pickle
from pathlib import Path

CODE = "510500"
SZ_CODE = f"sz{CODE}" if CODE.startswith(("1", "0", "2", "3")) else f"sh{CODE}"
SELL_MA = 10  # 卖出条件: 收盘 < MA{SELL_MA}
CACHE = Path(__file__).parent / "data_cache" / f"_{SZ_CODE}_sina.pkl"


def fetch_data():
    if CACHE.exists():
        with open(CACHE, "rb") as f:
            df = pickle.load(f)
        print(f"Loaded from cache: {len(df)} rows")
        return df

    url = (f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={SZ_CODE}&scale=240&datalen=800")
    r = requests.get(url, timeout=15)
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected response: {data}")

    df = pd.DataFrame(data)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns={"day": "date"})
    df = df.sort_values("date").reset_index(drop=True)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(df, f)

    print(f"Fetched from Sina: {len(df)} rows, {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    return df


def backtest(df):
    df["MA5"] = df["close"].rolling(window=5).mean()
    df["MA10"] = df["close"].rolling(window=10).mean()

    trades = []
    in_position = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0

    df["MA60"] = df["close"].rolling(window=60).mean()

    for i in range(60, len(df)):
        row = df.iloc[i]

        if not in_position:
            if row["close"] > row["MA60"]:
                in_position = True
                entry_price = row["close"]
                entry_date = row["date"]
                entry_idx = i
        else:
            stop_price = entry_price * 0.97
            if row["close"] < row["MA60"] or row["close"] < stop_price:
                exit_price = row["close"]
                exit_date = row["date"]
                pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
                label = f"+{pnl_pct}%" if pnl_pct >= 0 else f"{pnl_pct}%"
                trades.append({
                    "entry_date": entry_date, "entry_price": entry_price,
                    "exit_date": exit_date, "exit_price": exit_price,
                    "pnl_pct": pnl_pct, "label": label,
                    "days": i - entry_idx,
                })
                in_position = False

    if in_position:
        last = df.iloc[-1]
        pnl_pct = round((last["close"] - entry_price) / entry_price * 100, 2)
        label = f"+{pnl_pct}%" if pnl_pct >= 0 else f"{pnl_pct}%"
        trades.append({
            "entry_date": entry_date, "entry_price": entry_price,
            "exit_date": last["date"] + " (持仓)", "exit_price": last["close"],
            "pnl_pct": pnl_pct, "label": label,
            "days": len(df) - entry_idx,
        })

    return trades


def main():
    df = fetch_data()
    print(f"\nETF {CODE} 回测 | {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    print(f"最新价: {df['close'].iloc[-1]}")
    print(f"策略: 买=收盘>MA60 | 卖=收盘<MA60 或 -5%止损 | 均按收盘价\n")

    all_trades = backtest(df)

    # Filter: from May 2025
    cutoff = "2022-01-01"
    if df.iloc[-1]["date"] < cutoff:
        print("数据不足")
        return
    trades = [t for t in all_trades if t["entry_date"] >= cutoff]

    # Buy & Hold: close on cutoff day vs latest close
    cutoff_idx = df[df["date"] >= cutoff].index[0]
    bh_entry = df.loc[cutoff_idx, "close"]
    bh_exit = df.iloc[-1]["close"]
    bh_return = round((bh_exit - bh_entry) / bh_entry * 100, 2)

    print(f"\n===== {cutoff} ~ {df['date'].iloc[-1]} 回测 =====")
    print(f"买入持有收益: {bh_entry:.4f} -> {bh_exit:.4f} = {bh_return:+.2f}%\n")

    win = sum(1 for t in trades if t["pnl_pct"] > 0)
    total_pnl = sum(t["pnl_pct"] for t in trades)
    max_win = max((t["pnl_pct"] for t in trades), default=0)
    max_loss = min((t["pnl_pct"] for t in trades), default=0)

    if trades:
        print(f"{'买入日':<14} {'买入价':>8} {'卖出日':<16} {'卖出价':>8} {'盈亏%':>8} {'持有天':>5}")
        print("-" * 70)
        for t in trades:
            print(f"{t['entry_date']:<14} {t['entry_price']:>8.4f} "
                  f"{t['exit_date']:<16} {t['exit_price']:>8.4f} "
                  f"{t['label']:>8} {t['days']:>5}")

    win_rate = round(win / len(trades) * 100, 1) if trades else 0
    avg_pnl = round(total_pnl / len(trades), 2) if trades else 0
    print(f"\n{'=' * 70}")
    print(f"对比:  策略累计 {total_pnl:+.2f}%  vs  买入持有 {bh_return:+.2f}%")
    print(f"总交易: {len(trades)} 次")
    print(f"胜率:   {win}/{len(trades)} = {win_rate}%")
    print(f"最大盈利: +{max_win:.2f}% / 最大亏损: {max_loss:.2f}%")
    print(f"平均每次: {avg_pnl:+.2f}%")
    print(f"每笔按收盘价成交, 未计手续费")


if __name__ == "__main__":
    main()
