import streamlit as st
from datetime import datetime

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
    page_title="赏金猎人",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

apply_global_style()
render_header()

today_str = get_trading_date()
ALL_ETFS = SECTOR_ETFS + OVERSEAS_ETFS
start_date = get_start_date()

# ── 自动初始化 ──────────────────────────────────

APP_VERSION = "v4"  # 修改此值即可触发容器重新初始化

if st.session_state.get("app_version") != APP_VERSION:
    st.session_state.clear()
    st.session_state.app_version = APP_VERSION
    st.cache_data.clear()
    # 清除旧磁盘缓存（防止空缓存导致不调 API）
    from pathlib import Path
    for f in Path("data_cache").glob("*.pkl"):
        f.unlink()

# ── 全量转牛扫描（ETF + 个股，单次完成） ────────────────────────

def run_turn_bull_scan():
    st.session_state.bull_scanning = True
    try:
        with st.status("正在扫描转牛信号...", expanded=True) as status:
            st.write("获取ETF行情数据...")
            etf_data = fetch_etf_histories(start_date, etf_list=ALL_ETFS)
            st.write(f"✓ {len(etf_data)} 只ETF")
            etf_signals = scan_turn_bull_etfs(etf_data)

            st.write("获取大市值股票列表(≥100亿)...")
            stock_df = get_bigcap_stocks()
            stock_codes = stock_df["代码"].tolist()
            stock_name_map = dict(zip(stock_df["代码"], stock_df["名称"]))
            st.write(f"✓ {len(stock_codes)} 只")

            st.write("获取个股日线行情...")
            progress_bar = st.progress(0)
            progress_text = st.empty()
            def update_progress(completed, total):
                progress_bar.progress(min(completed / total, 1.0))
                progress_text.text(f"已处理 {completed}/{total}")
            histories = fetch_all_histories(
                stock_codes, start_date,
                progress_callback=update_progress,
            )
            st.write(f"✓ {len(histories)} 只股票日线数据")

            st.write("计算转牛信号...")
            stock_signals = scan_turn_bull_stocks(histories, stock_name_map)
            st.write(f"✓ 个股转牛 {len(stock_signals)} 只")

            status.update(
                label=f"转牛完成 — ETF {len(etf_signals)} 只, 个股 {len(stock_signals)} 只",
                state="complete", expanded=False,
            )
        st.session_state.bull_etf = etf_signals
        st.session_state.bull_stock = stock_signals
        st.session_state.bull_etf_done = True
        st.session_state.bull_stock_done = True
        st.session_state.bull_date = today_str
        now_hour = datetime.now().hour
        if now_hour >= 15:
            sh.save_turn_bull_snapshot(stock_signals, etf_signals)
    finally:
        st.session_state.bull_scanning = False


# ── 趋势扫描 ──────────────────────────────────────────────────────

def run_trend_scan():
    st.session_state.trend_scanning = True
    try:
        with st.status("正在扫描趋势信号...", expanded=True) as status:
            st.write("获取ETF行情数据...")
            etf_data = fetch_etf_histories(start_date, etf_list=ALL_ETFS)
            st.write(f"✓ {len(etf_data)} 只ETF")
            etf_signals = scan_trend_etfs(etf_data)

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
                label=f"趋势扫描完成 — ETF {len(etf_signals)} 只, 个股 {len(stock_signals)} 只",
                state="complete", expanded=False,
            )
        st.session_state.trend_etf = etf_signals
        st.session_state.trend_stock = stock_signals
        st.session_state.trend_done = True
        st.session_state.trend_date = today_str
        now_hour = datetime.now().hour
        if now_hour >= 15:
            sh.save_trend_snapshot(stock_signals, etf_signals)
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
- 今日涨跌幅 ≤ 7%

**ETF 额外宽松：** 近15日 ≥10天 收盘价 > MA5
""")
    if st.button("🔄 刷新趋势数据", type="primary", width='stretch', key="refresh_trend"):
        st.cache_data.clear()
        st.session_state.pop("trend_etf", None)
        st.session_state.pop("trend_stock", None)
        st.session_state.pop("trend_scanning", None)
        st.session_state.pop("trend_date", None)
        st.session_state.trend_done = False

    if st.session_state.get("trend_done") is False:
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
    st.caption(f"状态: done={st.session_state.get('bull_etf_done')} scan={st.session_state.get('bull_scanning')}")
    if st.button("🔄 刷新转牛数据", type="primary", width='stretch', key="refresh_bull"):
        st.cache_data.clear()
        st.session_state.pop("bull_etf", None)
        st.session_state.pop("bull_stock", None)
        st.session_state.pop("bull_scanning", None)
        st.session_state.pop("bull_date", None)
        st.session_state.bull_etf_done = False
        st.session_state.bull_stock_done = False

    _bull_done = st.session_state.get("bull_etf_done", False)
    if not _bull_done:
        try:
            run_turn_bull_scan()
        except Exception as ex:
            st.error(f"转牛扫描异常: {ex}")

    _bull_done = st.session_state.get("bull_etf_done", False)

    st.subheader("📊 ETF 转牛信号")
    bull_etf = st.session_state.get("bull_etf", [])
    if bull_etf:
        st.success(f"ETF转牛: {len(bull_etf)} 只")
    elif _bull_done:
        st.info("ETF转牛: 无满足条件")
    render_turn_bull_etf_results(bull_etf)

    st.subheader("📈 个股转牛信号")
    if _bull_done:
        bull_stock = st.session_state.get("bull_stock", [])
        if bull_stock:
            st.success(f"个股转牛: {len(bull_stock)} 只")
        else:
            st.info("个股转牛: 无满足条件")
        render_turn_bull_stock_results(bull_stock)

# ── Tab 3: 历史信号 ──────────────────────────────────────────────

with tab_history:
    st.subheader("📜 历史信号记录")
    dates = sh.get_available_dates()
    if not dates:
        st.info("暂无历史记录。完成一次扫描后，结果将自动保存在此处。")
    else:
        sel_date = st.selectbox("选择日期", dates, index=0)
        snap = sh.get_snapshot(sel_date)
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
                        st.write(f"{r.get('代码','')} {r.get('名称','')} {r.get('现价','')} {r.get('涨跌幅','')}")
                else:
                    st.caption("无")
            with col2:
                st.markdown(f"**ETF** ({len(tb_etfs)} 只)")
                if tb_etfs:
                    for r in tb_etfs:
                        st.write(f"{r.get('代码','')} {r.get('名称','')} {r.get('现价','')} {r.get('涨跌幅','')}")
                else:
                    st.caption("无")

            st.markdown(f"### 📈 趋势信号 — {sel_date}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**个股** ({len(tr_stocks)} 只)")
                if tr_stocks:
                    for r in tr_stocks:
                        st.write(f"{r.get('代码','')} {r.get('名称','')} {r.get('现价','')} {r.get('涨跌幅','')}")
                else:
                    st.caption("无")
            with col2:
                st.markdown(f"**ETF** ({len(tr_etfs)} 只)")
                if tr_etfs:
                    for r in tr_etfs:
                        st.write(f"{r.get('代码','')} {r.get('名称','')} {r.get('涨跌幅','')} ({r.get('现价','')})")
                else:
                    st.caption("无")
