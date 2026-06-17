import streamlit as st

from config import HISTORY_DAYS, SECTOR_ETFS, OVERSEAS_ETFS, get_trading_date
from fetcher import (
    get_bigcap_stocks, get_start_date,
    fetch_all_histories, fetch_etf_histories,
)
from signals import scan_turn_bull_stocks, scan_turn_bull_etfs, scan_trend_stocks, scan_trend_etfs
import signal_history as sh
from renderer import (
    apply_global_style, render_header,
    render_turn_bull_stock_results, render_turn_bull_etf_results,
    render_trend_stock_results, render_trend_etf_results,
)

st.set_page_config(
    page_title="蚂蚁上树",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

apply_global_style()

today_str = get_trading_date()
ALL_ETFS = SECTOR_ETFS + OVERSEAS_ETFS
start_date = get_start_date()



render_header()

# ── 自动初始化 ──────────────────────────────────

APP_VERSION = "v5"  # 修改此值即可触发容器重新初始化

if st.session_state.get("app_version") != APP_VERSION:
    st.session_state.clear()
    st.session_state.app_version = APP_VERSION
    st.cache_data.clear()
    from pathlib import Path
    for f in Path("data_cache").glob("*.pkl"):
        if f.name != "signal_history.pkl":
            f.unlink()

# ── 从历史信号恢复最近数据（避免重复扫描） ─────────────────────

@st.cache_data(ttl=86400)
def _get_cached_snapshot(date):
    return sh.get_snapshot(date)

_loaded_from_history = False
if not st.session_state.pop("_refresh_requested", False):
    _dates = sh.get_available_dates()
    _snap_date = today_str if sh.get_snapshot(today_str) else (_dates[0] if _dates else None)
    if _snap_date:
        _snap = _get_cached_snapshot(_snap_date)
        if _snap:
            tb = _snap.get("turn_bull", {})
            tr = _snap.get("trend", {})
            if tb.get("stocks") or tb.get("etfs"):
                st.session_state.bull_stock = tb.get("stocks", [])
                st.session_state.bull_etf = tb.get("etfs", [])
                st.session_state.bull_etf_done = True
                st.session_state.bull_stock_done = True
                st.session_state.bull_date = _snap_date
            if tr.get("stocks") or tr.get("etfs"):
                st.session_state.trend_stock = tr.get("stocks", [])
                st.session_state.trend_etf = tr.get("etfs", [])
                st.session_state.trend_done = True
                st.session_state.trend_date = _snap_date
            if tb.get("stocks") or tb.get("etfs") or tr.get("stocks") or tr.get("etfs"):
                _loaded_from_history = True
    if _loaded_from_history and _snap_date != today_str:
        st.caption(f"📌 当前显示 {_snap_date} 数据（今日尚未扫描）")

# ── 转牛ETF快速扫描（个股不在此处扫描） ────────────────────────────

def run_turn_bull_scan():
    st.session_state.bull_scanning = True
    try:
        with st.status("正在扫描转牛ETF...", expanded=True) as status:
            st.write("获取ETF行情数据...")
            etf_data = fetch_etf_histories(start_date, etf_list=ALL_ETFS)
            st.write(f"✓ {len(etf_data)} 只ETF")
            etf_signals = scan_turn_bull_etfs(etf_data)
            status.update(
                label=f"转牛ETF: {len(etf_signals)} 只",
                state="complete", expanded=False,
            )
        st.session_state.bull_etf = etf_signals
        st.session_state.bull_etf_done = True
        st.session_state.bull_date = today_str
        sh.save_turn_bull_snapshot([], etf_signals)
        _get_cached_snapshot.clear()
        sh.sync_remote()
    finally:
        st.session_state.bull_scanning = False


# ── 趋势扫描（含转牛ETF） ──────────────────────────────────────────

def run_trend_scan():
    st.session_state.trend_scanning = True
    try:
        with st.status("正在扫描信号...", expanded=True) as status:
            st.write("获取ETF行情数据...")
            etf_data = fetch_etf_histories(start_date, etf_list=ALL_ETFS)
            st.write(f"✓ {len(etf_data)} 只ETF")
            etf_signals = scan_trend_etfs(etf_data)
            bull_etf_signals = scan_turn_bull_etfs(etf_data)

            st.write("获取大市值股票行情(≥100亿)...")
            stock_df = get_bigcap_stocks()
            stock_codes = stock_df["代码"].tolist()
            stock_name_map = dict(zip(stock_df["代码"], stock_df["名称"]))
            progress_bar = st.progress(0)
            progress_text = st.empty()
            def update_progress(completed, total):
                progress_bar.progress(min(completed / total, 1.0))
                progress_text.text(f"已处理 {completed}/{total}")
            histories = fetch_all_histories(stock_codes, start_date, progress_callback=update_progress)
            st.write(f"✓ {len(histories)} 只股票")
            stock_signals = scan_trend_stocks(histories, stock_name_map)
            st.write(f"个股趋势信号: {len(stock_signals)} 只")

            status.update(
                label=f"趋势 {len(stock_signals)}只股 {len(etf_signals)}只ETF | 转牛ETF {len(bull_etf_signals)}只",
                state="complete", expanded=False,
            )
        st.session_state.trend_etf = etf_signals
        st.session_state.trend_stock = stock_signals
        st.session_state.trend_done = True
        st.session_state.trend_date = today_str
        st.session_state.bull_etf = bull_etf_signals
        st.session_state.bull_etf_done = True
        st.session_state.bull_date = today_str
        sh.save_trend_snapshot(stock_signals, etf_signals)
        sh.save_turn_bull_snapshot([], bull_etf_signals)
        _trend_codes = {r["代码"] for r in stock_signals}
        st.session_state.trend_missed = sh.compute_and_save_today_missed(_trend_codes)
        _get_cached_snapshot.clear()
        sh.sync_remote()
    finally:
        st.session_state.trend_scanning = False


# ══════════════════════════════════════════════════════════════════
#  页面布局
# ══════════════════════════════════════════════════════════════════

tab_trend, tab_bull, tab_history = st.tabs(["📈 趋势信号", "🔄 转牛信号", "📜 历史信号"])

# ── Tab 1: 趋势信号 ──────────────────────────────────────────────

with tab_trend:
    with st.expander("📋 趋势选股策略说明"):
        st.markdown("""
**核心逻辑：中期均线多头排列，未过度透支**

- 近13日中 ≥10天 收盘价 > MA5
- 近13日 全部 收盘价 > MA15
- 今日收盘价 > MA5
- 今日涨跌幅 -7% ~ +10%（排除大跌和涨停）

**ETF 额外宽松：** 近15日 ≥10天 收盘价 > MA5
""")
    if st.button("🔄 刷新趋势数据", type="primary", width='stretch', key="refresh_trend"):
        st.cache_data.clear()
        st.session_state._refresh_requested = True
        st.session_state.pop("trend_etf", None)
        st.session_state.pop("trend_stock", None)
        st.session_state.pop("trend_scanning", None)
        st.session_state.pop("trend_date", None)
        st.session_state.trend_done = False
        st.rerun()

    _done = st.session_state.get("trend_done")
    if _done is None:
        st.info("点击上方按钮开始扫描")
    elif not _done:
        try:
            run_trend_scan()
        except Exception as ex:
            st.error(f"趋势扫描异常: {ex}")

    _done = st.session_state.get("trend_done")

    st.subheader("📊 ETF 趋势信号")
    trend_etf = st.session_state.get("trend_etf", [])
    if trend_etf:
        st.success(f"ETF趋势: {len(trend_etf)} 只")
    elif _done:
        st.info("ETF: 无满足条件")
    render_trend_etf_results(trend_etf)

    st.subheader("📈 个股趋势信号")
    if _done:
        trend_stock = st.session_state.get("trend_stock", [])
        if trend_stock:
            st.success(f"个股趋势: {len(trend_stock)} 只")
        else:
            st.info("个股: 无满足条件")
        render_trend_stock_results(trend_stock)

# ── Tab 2: 转牛信号 ─────────────────────────────────────────────

with tab_bull:
    with st.expander("📋 转牛选股策略说明"):
        st.markdown("""
**核心逻辑：弱势股首次突破60日均线**

1. 近30日中 ≥20天 收盘价 < MA60（确认前期弱势）
2. 今日收盘站上MA60（首次突破）
   - 或昨日首次站上 + 今日确认
""")
    if st.button("🔄 刷新转牛ETF数据", type="primary", width='stretch', key="refresh_bull"):
        st.cache_data.clear()
        st.session_state._refresh_requested = True
        st.session_state.pop("bull_etf", None)
        st.session_state.pop("bull_scanning", None)
        st.session_state.pop("bull_date", None)
        st.session_state.bull_etf_done = False
        st.rerun()

    st.caption(f"状态: done={st.session_state.get('bull_etf_done')} scan={st.session_state.get('bull_scanning')}（趋势扫描时自动含转牛ETF）")
    _bull_done = st.session_state.get("bull_etf_done")
    if _bull_done is None:
        st.info("运行趋势扫描，或点击上方按钮单独刷新转牛ETF")
    elif not _bull_done:
        try:
            run_turn_bull_scan()
        except Exception as ex:
            st.error(f"转牛扫描异常: {ex}")

    _bull_done = st.session_state.get("bull_etf_done")

    st.subheader("📊 ETF 转牛信号")
    bull_etf = st.session_state.get("bull_etf", [])
    if bull_etf:
        st.success(f"ETF转牛: {len(bull_etf)} 只")
    elif _bull_done:
        st.info("ETF转牛: 无满足条件")
    render_turn_bull_etf_results(bull_etf)

# ── Tab 3: 历史信号 ──────────────────────────────────────────────

with tab_history:
    st.subheader("📜 历史信号记录")
    dates = sh.get_available_dates()
    if not dates:
        st.info("暂无历史记录。完成一次扫描后，结果将自动保存在此处。")
    else:
        sel_date = st.selectbox("选择日期", dates, index=0)
        latest_date = dates[0]
        snap = sh.get_snapshot(sel_date)
        resurgence = sh.get_resurgence(sel_date, latest_date) if snap else set()
        _trend_missed = set(st.session_state.get("trend_missed", [])) if st.session_state.get("trend_done") else set()
        if snap:
            tb_stocks = snap.get("turn_bull", {}).get("stocks", [])
            tb_etfs = snap.get("turn_bull", {}).get("etfs", [])
            tr_stocks = snap.get("trend", {}).get("stocks", [])
            tr_etfs = snap.get("trend", {}).get("etfs", [])

            st.markdown(f"### 🔄 转牛信号 — {sel_date}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**个股** ({len(tb_stocks)} 只)")
                if tb_stocks:
                    for r in tb_stocks:
                        code = r.get('代码','')
                        tag = " 🔥" if (code in resurgence or code in _trend_missed) else ""
                        st.write(f"{code} {r.get('名称','')} {r.get('现价','')} {r.get('涨跌幅','')}{tag}")
                else:
                    st.caption("无")
            with col2:
                st.markdown(f"**ETF** ({len(tb_etfs)} 只)")
                if tb_etfs:
                    for r in tb_etfs:
                        code = r.get('代码','')
                        tag = " 🔥" if (code in resurgence or code in _trend_missed) else ""
                        st.write(f"{code} {r.get('名称','')} {r.get('现价','')} {r.get('涨跌幅','')}{tag}")
                else:
                    st.caption("无")

            st.markdown(f"### 📈 趋势信号 — {sel_date}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**个股** ({len(tr_stocks)} 只)")
                if tr_stocks:
                    for r in tr_stocks:
                        code = r.get('代码','')
                        tag = " 🔥" if (code in resurgence or code in _trend_missed) else ""
                        st.write(f"{code} {r.get('名称','')} {r.get('现价','')} {r.get('涨跌幅','')}{tag}")
                else:
                    st.caption("无")
            with col2:
                st.markdown(f"**ETF** ({len(tr_etfs)} 只)")
                if tr_etfs:
                    for r in tr_etfs:
                        code = r.get('代码','')
                        tag = " 🔥" if (code in resurgence or code in _trend_missed) else ""
                        st.write(f"{code} {r.get('名称','')} {r.get('涨跌幅','')} ({r.get('现价','')}){tag}")
                else:
                    st.caption("无")
