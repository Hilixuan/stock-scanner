"""MA60策略: 收盘≥MA60买入 / 收盘≤MA60卖出 | 2023-05 ~ 现在"""
import requests, pandas as pd, pickle, statistics
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)

SORT = False  # set True to sort by strategy return descending

ETFS = [
    ("513100", "纳指ETF"),
    ("510300", "沪深300ETF"),
    ("510050", "上证50ETF"),
    ("588000", "科创50ETF"),
    ("159915", "创业板ETF"),
    ("159949", "创业板50ETF"),
    ("512880", "证券ETF"),
    ("510880", "红利ETF"),
    ("512010", "医药ETF"),
    ("159766", "旅游ETF"),
    ("159865", "养殖ETF"),
    ("516150", "稀土ETF"),
    ("518880", "黄金ETF"),
    ("513050", "中概互联ETF"),
    ("561310", "半导体材料ETF"),
    ("159552", "中证2000增强ETF"),
]


def sina_symbol(code):
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{code}"


def fetch(code):
    sym = sina_symbol(code)
    path = CACHE_DIR / f"_{sym}_sina.pkl"
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sym}&scale=240&datalen=800"
    r = requests.get(url, timeout=15)
    data = r.json()
    df = pd.DataFrame(data)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns={"day": "date"}).sort_values("date").reset_index(drop=True)
    with open(path, "wb") as f:
        pickle.dump(df, f)
    return df


def backtest(df):
    df["MA60"] = df["close"].rolling(60).mean()

    trades = []
    in_pos = False
    ep, ed, ei = 0, "", 0

    for i in range(60, len(df)):
        row = df.iloc[i]
        if not in_pos:
            if row["close"] >= row["MA60"]:
                in_pos = True
                ep, ed, ei = row["close"], row["date"], i
        else:
            if row["close"] <= row["MA60"]:
                pnl = round((row["close"] - ep) / ep * 100, 2)
                trades.append({"entry": ed, "ep": ep, "exit": row["date"], "xp": row["close"], "pnl": pnl, "days": i - ei})
                in_pos = False

    if in_pos:
        last = df.iloc[-1]
        pnl = round((last["close"] - ep) / ep * 100, 2)
        trades.append({"entry": ed, "ep": ep, "exit": "持仓", "xp": last["close"], "pnl": pnl, "days": len(df) - ei})

    return trades, df


def compound(trades):
    cash = 100000
    for t in trades:
        cash *= (1 + t["pnl"] / 100)
    return round(cash, 0)


def max_dd(trades):
    if not trades:
        return 0
    peak = 100000
    dd = 0
    cash = 100000
    for t in trades:
        cash *= (1 + t["pnl"] / 100)
        if cash > peak:
            peak = cash
        dd = min(dd, round((cash - peak) / peak * 100, 2))
    return dd


print(f"{'ETF':<14} {'代码':>6} {'交易':>4} {'胜率':>5} {'累计%':>8} {'终值':>10} {'回撤':>7} {'持有%':>8}")
print("=" * 75)

rows = []

for code, name in ETFS:
    df = fetch(code)
    cutoff = "2023-05-01"
    idx = df[df["date"] >= cutoff].index[0]
    df_cut = df.loc[idx:].reset_index(drop=True)

    trades, _ = backtest(df_cut)

    if not trades:
        continue

    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_pnl = sum(t["pnl"] for t in trades)
    final = compound(trades)
    dd = max_dd(trades)
    wr = round(wins / len(trades) * 100, 1)

    # Buy & hold
    bh_ep = df_cut.iloc[0]["close"]
    bh_xp = df_cut.iloc[-1]["close"]
    bh = round((bh_xp - bh_ep) / bh_ep * 100, 2)

    rows.append((total_pnl, name, code, len(trades), wr, total_pnl, final, dd, bh))
    print(f"{name:<14} {code:>6} {len(trades):>4} {wr:>4}% {total_pnl:>+7.2f}% {final:>10.0f} {dd:>6.2f}% {bh:>+7.2f}%")
