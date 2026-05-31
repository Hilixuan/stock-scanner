import pandas as pd
from config import GOLDEN_CROSS_SHORT_MA, GOLDEN_CROSS_LONG_MA, VOLUME_RATIO


def check_golden_cross(df):
    if df is None or len(df) < GOLDEN_CROSS_LONG_MA:
        return False, None

    df = df.copy()
    df = df.sort_values("日期").reset_index(drop=True)

    df["MA_Short"] = df["收盘"].rolling(window=GOLDEN_CROSS_SHORT_MA).mean()
    df["MA_Long"] = df["收盘"].rolling(window=GOLDEN_CROSS_LONG_MA).mean()
    df["MA_Vol"] = df["成交量"].rolling(window=5).mean()

    if len(df) < 2:
        return False, df

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    cross_up = (
        latest["MA_Short"] > latest["MA_Long"]
        and prev["MA_Short"] <= prev["MA_Long"]
    )

    vol_confirmed = (
        latest["MA_Vol"] > 0
        and latest["成交量"] > VOLUME_RATIO * latest["MA_Vol"]
    )

    return cross_up and vol_confirmed, df


def scan_stocks(histories, stock_name_map):
    signals = []
    for code, df in histories.items():
        try:
            is_signal, detail_df = check_golden_cross(df)
            if is_signal:
                latest = detail_df.iloc[-1]
                prev = detail_df.iloc[-2]
                signals.append({
                    "代码": code,
                    "名称": stock_name_map.get(code, ""),
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "成交量": int(latest["成交量"]),
                    "量比": round(float(latest["成交量"] / latest["MA_Vol"]), 2) if latest["MA_Vol"] > 0 else 0,
                    f"MA{GOLDEN_CROSS_SHORT_MA}": round(float(latest["MA_Short"]), 2),
                    f"MA{GOLDEN_CROSS_LONG_MA}": round(float(latest["MA_Long"]), 2),
                    "prev_MA_Short": round(float(prev["MA_Short"]), 2),
                    "prev_MA_Long": round(float(prev["MA_Long"]), 2),
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return signals


def scan_etfs(etf_data):
    signals = []
    for code, info in etf_data.items():
        try:
            is_signal, detail_df = check_golden_cross(info["data"])
            if is_signal:
                latest = detail_df.iloc[-1]
                prev = detail_df.iloc[-2]
                signals.append({
                    "代码": code,
                    "名称": info["name"],
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "成交量": int(latest["成交量"]),
                    "量比": round(float(latest["成交量"] / latest["MA_Vol"]), 2) if latest["MA_Vol"] > 0 else 0,
                    f"MA{GOLDEN_CROSS_SHORT_MA}": round(float(latest["MA_Short"]), 2),
                    f"MA{GOLDEN_CROSS_LONG_MA}": round(float(latest["MA_Long"]), 2),
                    "prev_MA_Short": round(float(prev["MA_Short"]), 2),
                    "prev_MA_Long": round(float(prev["MA_Long"]), 2),
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return signals


def check_ma_cross(df, short_ma=5, long_ma=10):
    if df is None or len(df) < long_ma:
        return None, None

    df = df.copy()
    df = df.sort_values("日期").reset_index(drop=True)
    df["MA_Short"] = df["收盘"].rolling(window=short_ma).mean()
    df["MA_Long"] = df["收盘"].rolling(window=long_ma).mean()

    if len(df) < 2:
        return None, df

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    golden = latest["MA_Short"] > latest["MA_Long"] and prev["MA_Short"] <= prev["MA_Long"]
    death = latest["MA_Short"] < latest["MA_Long"] and prev["MA_Short"] >= prev["MA_Long"]

    if golden:
        return "buy", df
    if death:
        return "sell", df
    if latest["MA_Short"] > latest["MA_Long"]:
        return "above", df
    return "below", df


# ── 转牛选股法 ──────────────────────────────────────────────────────

def check_turn_bull(df):
    """
    转牛条件:
      1. 近30日中大部分时间收盘<MA60 (已有逻辑)
      2. 今日收盘首次站上MA60 OR (昨日首次站上MA60且今日也站上)
    """
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

    # 首次突破检测
    above = df["收盘"] > df["MA60"]
    window = above.iloc[-(check_days + 1):]
    today_above = window.iloc[-1]
    yesterday_above = window.iloc[-2] if len(window) >= 2 else False
    past_before_today = window.iloc[:-1]
    past_before_yesterday = window.iloc[:-2] if len(window) > 2 else pd.Series([], dtype=bool)

    # Case 1: 今日首次站上
    if today_above and not past_before_today.any():
        return True, df
    # Case 2: 昨日首次站上 + 今日确认
    if yesterday_above and today_above and not past_before_yesterday.any():
        return True, df
    return False, df


def scan_turn_bull_stocks(histories, stock_name_map):
    signals = []
    for code, df in histories.items():
        try:
            mcap = df.get("总市值(亿)", pd.Series([0])).iloc[-1]
            if mcap < 100:
                continue
            is_signal, detail_df = check_turn_bull(df)
            if is_signal:
                latest = detail_df.iloc[-1]
                signals.append({
                    "代码": code,
                    "名称": stock_name_map.get(code, ""),
                    "总市值(亿)": round(mcap, 0),
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "MA5": round(float(latest["MA5"]), 2),
                    "MA60": round(float(latest["MA60"]), 2),
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return signals


def scan_turn_bull_etfs(etf_data):
    signals = []
    for code, info in etf_data.items():
        try:
            is_signal, detail_df = check_turn_bull(info["data"])
            if is_signal:
                latest = detail_df.iloc[-1]
                signals.append({
                    "代码": code,
                    "名称": info["name"],
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "MA5": round(float(latest["MA5"]), 2),
                    "MA60": round(float(latest["MA60"]), 2),
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return signals


# ── 趋势选股法 ──────────────────────────────────────────────────────

def check_trend(df):
    """趋势条件: 近15日 ≥12天收盘>MA5, 且15天全部收盘>MA15"""
    if df is None or len(df) < 30:
        return False, None
    df = df.copy().sort_values("日期").reset_index(drop=True)
    df["MA5"] = df["收盘"].rolling(5).mean()
    df["MA15"] = df["收盘"].rolling(15).mean()
    valid = df["MA15"].notna()
    if valid.sum() < 15:
        return False, df
    last15 = df[valid].iloc[-15:]
    above_ma5 = (last15["收盘"] > last15["MA5"]).sum()
    above_ma15 = (last15["收盘"] > last15["MA15"]).sum()
    return (above_ma5 >= 12 and above_ma15 == 15), df


def scan_trend_stocks(histories, stock_name_map):
    signals = []
    for code, df in histories.items():
        try:
            mcap = df.get("总市值(亿)", pd.Series([0])).iloc[-1]
            if mcap < 100:
                continue
            is_signal, detail_df = check_trend(df)
            if is_signal:
                latest = detail_df.iloc[-1]
                signals.append({
                    "代码": code,
                    "名称": stock_name_map.get(code, ""),
                    "总市值(亿)": round(mcap, 0),
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "MA5": round(float(latest["MA5"]), 2),
                    "MA15": round(float(latest["MA15"]), 2),
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return signals


def check_trend_etf(df):
    """ETF趋势条件: 近15日 ≥10天收盘>MA5, 且15天全部收盘>MA15"""
    if df is None or len(df) < 30:
        return False, None
    df = df.copy().sort_values("日期").reset_index(drop=True)
    df["MA5"] = df["收盘"].rolling(5).mean()
    df["MA15"] = df["收盘"].rolling(15).mean()
    valid = df["MA15"].notna()
    if valid.sum() < 15:
        return False, df
    last15 = df[valid].iloc[-15:]
    above_ma5 = (last15["收盘"] > last15["MA5"]).sum()
    above_ma15 = (last15["收盘"] > last15["MA15"]).sum()
    return (above_ma5 >= 10 and above_ma15 == 15), df


def scan_trend_etfs(etf_data):
    signals = []
    for code, info in etf_data.items():
        try:
            is_signal, detail_df = check_trend_etf(info["data"])
            if is_signal:
                latest = detail_df.iloc[-1]
                signals.append({
                    "代码": code,
                    "名称": info["name"],
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "MA5": round(float(latest["MA5"]), 2),
                    "MA15": round(float(latest["MA15"]), 2),
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return signals


def etf_full_scan(etf_data):
    results = []
    for code, info in etf_data.items():
        try:
            signal_type, detail_df = check_ma_cross(info["data"])
            if detail_df is not None:
                latest = detail_df.iloc[-1]
                prev = detail_df.iloc[-2]
                results.append({
                    "代码": code,
                    "名称": info["name"],
                    "现价": round(float(latest["收盘"]), 2),
                    "涨跌幅": f"{latest.get('涨跌幅', 0):+.2f}%",
                    "涨跌幅值": float(latest.get("涨跌幅", 0)),
                    "MA5": round(float(latest["MA_Short"]), 2),
                    "MA10": round(float(latest["MA_Long"]), 2),
                    "prev_MA5": round(float(prev["MA_Short"]), 2),
                    "prev_MA10": round(float(prev["MA_Long"]), 2),
                    "signal_raw": signal_type,
                    "_detail_df": detail_df,
                })
        except Exception:
            pass
    return results
