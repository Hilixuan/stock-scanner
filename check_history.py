import pickle
f = "data_cache/signal_history.pkl"
try:
    with open(f, "rb") as fh:
        d = pickle.load(fh)
    for date in sorted(d.keys()):
        tb = d[date].get("turn_bull", {})
        tr = d[date].get("trend", {})
        stocks_tb = tb.get("stocks", [])
        etfs_tb = tb.get("etfs", [])
        stocks_tr = tr.get("stocks", [])
        etfs_tr = tr.get("etfs", [])
        print(f"{date}: tb_stock={len(stocks_tb)} tb_etf={len(etfs_tb)} tr_stock={len(stocks_tr)} tr_etf={len(etfs_tr)}")
except Exception as e:
    print(f"Error: {e}")
    import os
    print(f"File exists: {os.path.exists(f)}")
    if os.path.exists(f):
        print(f"File size: {os.path.getsize(f)}")
