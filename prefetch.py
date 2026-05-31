"""
Standalone prefetch script for Windows Task Scheduler.

Usage:
    python prefetch.py                  # fetch all
    python prefetch.py --stocks         # stock list only
    python prefetch.py --histories      # stock histories (includes market cap filter >=50亿)
    python prefetch.py --etfs           # ETF histories only

Logs: prefetch.log
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

import baostock as bs

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from config import HISTORY_DAYS, SECTOR_ETFS, OVERSEAS_ETFS
from fetcher import (
    CACHE_DIR, STOCK_LIST_FILE, ALL_HISTORIES_FILE, ALL_ETFS_FILE,
    get_start_date, get_stock_list, fetch_all_histories,
    _disk_save, _disk_load, _ensure_cache_dir,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "prefetch.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("prefetch")


def fetch_stock_list():
    log.info("Fetching stock list…")
    df = get_stock_list()
    log.info("Stock list saved: %d stocks", len(df))
    return True


def fetch_all_stock_histories():
    cached = _disk_load(STOCK_LIST_FILE)
    if cached is None:
        log.warning("Stock list not found, fetching first…")
        fetch_stock_list()
        cached = _disk_load(STOCK_LIST_FILE)

    codes = cached["代码"].tolist()
    start = get_start_date()

    log.info("Fetching histories for %d stocks (market cap filter >= 50亿)…", len(codes))
    results = fetch_all_histories(codes, start)
    log.info("After market cap filter: %d stocks saved", len(results))
    return True


def fetch_etf_histories():
    etf_list = SECTOR_ETFS + OVERSEAS_ETFS
    log.info("Fetching %d ETF histories…", len(etf_list))

    start = get_start_date()
    end = datetime.now().strftime("%Y-%m-%d")

    name_map = dict(etf_list)

    lg = bs.login()
    if lg.error_code != "0":
        log.error("baostock login failed: %s", lg.error_msg)
        return False
    try:
        results = {}
        for code, name in etf_list:
            try:
                prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
                rs = bs.query_history_k_data_plus(
                    f"{prefix}.{code}",
                    "date,open,high,low,close,preclose,volume,amount,pctChg",
                    start_date=start, end_date=end,
                    frequency="d", adjustflag="2",
                )
                if rs.error_code != "0":
                    continue
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows and len(rows) >= 30:
                    import pandas as pd
                    df = pd.DataFrame(rows, columns=[
                        "日期", "开盘", "最高", "最低", "收盘",
                        "昨收", "成交量", "成交额", "涨跌幅",
                    ])
                    for col in ["开盘", "最高", "最低", "收盘", "昨收",
                                "成交量", "成交额", "涨跌幅"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    results[code] = {"name": name, "data": df}
            except Exception as e:
                log.debug("Error fetching ETF %s: %s", code, e)
    finally:
        bs.logout()

    _disk_save(results, ALL_ETFS_FILE)
    log.info("ETF histories saved: %d ETFs", len(results))
    return True


def main():
    _ensure_cache_dir()

    tasks = {
        "--stocks": fetch_stock_list,
        "--histories": fetch_all_stock_histories,
        "--etfs": fetch_etf_histories,
    }

    args = set(sys.argv[1:])
    if not args or "-h" in args or "--help" in args:
        print(__doc__)
        return

    do_all = not any(a in tasks for a in args) or "--all" in args

    results = []
    if do_all:
        log.info("=== Prefetch ALL ===")
        for name, fn in tasks.items():
            log.info("--- %s ---", name)
            results.append(fn())
    else:
        for arg in args:
            if arg in tasks:
                log.info("--- %s ---", arg)
                results.append(tasks[arg]())

    ok = all(results)
    log.info("Prefetch %s", "completed" if ok else "failed (see above)")


if __name__ == "__main__":
    main()
