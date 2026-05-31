import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from config import GOLDEN_CROSS_SHORT_MA, GOLDEN_CROSS_LONG_MA


def apply_global_style():
    st.markdown("""
    <style>
    .block-container { padding: 1rem 1rem 2rem !important; max-width: 800px; }
    h1, h2, h3 { margin-bottom: 0.5rem !important; }
    .stMetric { background: #F0F2F6; padding: 0.8rem 1rem; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
    .stMetric label { font-size: 0.8rem !important; }
    .stMetric [data-testid="stMetricValue"] { font-size: 1.5rem !important; font-weight: 700; }
    div[data-testid="stStatusWidget"] { font-size: 0.9rem; }
    .stock-card { background: white; border: 1px solid #E8ECF0; border-radius: 12px; padding: 0.8rem 1rem; margin-bottom: 0.5rem; }
    .etf-section { margin-top: 1.5rem; }
    </style>
    """, unsafe_allow_html=True)


def render_header():
    st.title("赏金猎人")


def render_metrics(stock_count, etf_count, scan_date):
    cols = st.columns(3)
    cols[0].metric("金叉股票", f"{stock_count} 只")
    cols[1].metric("金叉ETF", f"{etf_count} 只")
    cols[2].metric("数据日期", scan_date)


def render_stock_results(signals):
    if not signals:
        st.info("当前无满足条件的金叉信号")
        return

    df = pd.DataFrame(signals)
    display_cols = ["代码", "名称", "现价", "涨跌幅", "量比",
                    f"MA{GOLDEN_CROSS_SHORT_MA}", f"MA{GOLDEN_CROSS_LONG_MA}"]

    display_df = df[display_cols].copy()

    def _color(val):
        if isinstance(val, str) and val.startswith("+"):
            return "color: #E53935; font-weight: 600"
        if isinstance(val, str) and val.startswith("-"):
            return "color: #43A047; font-weight: 600"
        return ""

    styled = display_df.style.map(_color, subset=["涨跌幅"])
    styled = styled.format({
        "现价": "{:.2f}",
        f"MA{GOLDEN_CROSS_SHORT_MA}": "{:.2f}",
        f"MA{GOLDEN_CROSS_LONG_MA}": "{:.2f}",
        "量比": "{:.2f}",
    })

    st.subheader("个股金叉信号")
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(60 + len(df) * 38, 600),
    )

    st.subheader("详情查看")
    for _, row in df.iterrows():
        with st.expander(f"{row['名称']} ({row['代码']}) — 现价 {row['现价']}"):
            detail_df = row["_detail_df"]
            if detail_df is not None:
                fig = _build_chart(detail_df, row["名称"])
                st.plotly_chart(fig, use_container_width=True)


def render_etf_results(signals):
    _render_etf_section(signals, "行业ETF金叉信号")


def render_overseas_etf_results(signals):
    _render_etf_section(signals, "海外ETF金叉信号")


def _render_etf_section(signals, title):
    if not signals:
        st.info(f"当前无满足金叉条件的{title.replace('金叉信号', '')}")
        return

    df = pd.DataFrame(signals)
    display_cols = ["代码", "名称", "现价", "涨跌幅", "量比",
                    f"MA{GOLDEN_CROSS_SHORT_MA}", f"MA{GOLDEN_CROSS_LONG_MA}"]

    display_df = df[display_cols].copy()

    def _color(val):
        if isinstance(val, str) and val.startswith("+"):
            return "color: #E53935; font-weight: 600"
        if isinstance(val, str) and val.startswith("-"):
            return "color: #43A047; font-weight: 600"
        return ""

    styled = display_df.style.map(_color, subset=["涨跌幅"])
    styled = styled.format({
        "现价": "{:.2f}",
        f"MA{GOLDEN_CROSS_SHORT_MA}": "{:.2f}",
        f"MA{GOLDEN_CROSS_LONG_MA}": "{:.2f}",
        "量比": "{:.2f}",
    })

    st.subheader(title)
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(60 + len(df) * 38, 400),
    )

    for _, row in df.iterrows():
        with st.expander(f"{row['名称']} ({row['代码']}) — 现价 {row['现价']}"):
            detail_df = row["_detail_df"]
            if detail_df is not None:
                fig = _build_chart(detail_df, row["名称"])
                st.plotly_chart(fig, use_container_width=True)


def _render_signal_table(signals, extra_cols=None, ma_cols=None, chart_fn=None):
    if not signals:
        st.info("无满足条件的信号")
        return
    if ma_cols is None:
        ma_cols = ["MA5", "MA60"]
    if chart_fn is None:
        chart_fn = _build_turn_bull_chart
    df = pd.DataFrame(signals)
    cols = ["代码", "名称"] + (extra_cols or []) + ["现价", "涨跌幅"] + list(ma_cols)
    display_df = df[[c for c in cols if c in df.columns]].copy()

    def _color(val):
        if isinstance(val, str) and val.startswith("+"):
            return "color: #E53935; font-weight: 600"
        if isinstance(val, str) and val.startswith("-"):
            return "color: #43A047; font-weight: 600"
        return ""

    fmt = {"现价": "{:.2f}"}
    for c in ma_cols:
        fmt[c] = "{:.2f}"
    if "总市值(亿)" in display_df.columns:
        fmt["总市值(亿)"] = "{:.0f}"
    styled = display_df.style.map(_color, subset=["涨跌幅"])
    styled = styled.format(fmt)
    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(60 + len(df) * 38, 600))
    for _, row in df.iterrows():
        with st.expander(f"{row['名称']} ({row['代码']}) — ¥{row['现价']}"):
            detail_df = row.get("_detail_df")
            if detail_df is not None:
                fig = chart_fn(detail_df, row["名称"])
                st.plotly_chart(fig, use_container_width=True)


def render_turn_bull_stock_results(signals):
    _render_signal_table(signals, extra_cols=["总市值(亿)"])


def render_turn_bull_etf_results(signals):
    _render_signal_table(signals)


def render_trend_stock_results(signals):
    _render_signal_table(signals, extra_cols=["总市值(亿)"], ma_cols=["MA5", "MA15"], chart_fn=_build_trend_chart)


def render_trend_etf_results(signals):
    _render_signal_table(signals, ma_cols=["MA5", "MA15"], chart_fn=_build_trend_chart)


def _build_ma_chart_base(df, title, ma_specs):
    df = df.sort_values("日期").tail(120)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df["日期"], open=df["开盘"], high=df["最高"], low=df["最低"], close=df["收盘"],
                                 name="K线", showlegend=False, increasing_line_color="#E53935", decreasing_line_color="#43A047"), row=1, col=1)
    for col, label, color in ma_specs:
        fig.add_trace(go.Scatter(x=df["日期"], y=df[col], line=dict(color=color, width=1.5), name=label), row=1, col=1)
    colors = ["#43A047" if v >= 0 else "#E53935" for v in df["涨跌幅"]]
    fig.add_trace(go.Bar(x=df["日期"], y=df["成交量"], name="成交量", marker_color=colors, showlegend=False), row=2, col=1)
    fig.update_layout(title=dict(text=title, font=dict(size=14)), height=420, margin=dict(l=20, r=20, t=40, b=20),
                      template="plotly_white", hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)))
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    return fig


def _build_turn_bull_chart(df, title):
    return _build_ma_chart_base(df, title, [("MA5", "MA5", "#FFA726"), ("MA60", "MA60", "#42A5F5")])


def _build_trend_chart(df, title):
    return _build_ma_chart_base(df, title, [("MA5", "MA5", "#FFA726"), ("MA15", "MA15", "#42A5F5")])


def _build_chart(df, title):
    return _build_ma_chart(df, title, GOLDEN_CROSS_SHORT_MA, GOLDEN_CROSS_LONG_MA)


def _build_ma_chart(df, title, short_ma, long_ma):
    df = df.sort_values("日期").tail(90)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
    )

    fig.add_trace(go.Candlestick(
        x=df["日期"],
        open=df["开盘"], high=df["最高"],
        low=df["最低"], close=df["收盘"],
        name="K线", showlegend=False,
        increasing_line_color="#E53935",
        decreasing_line_color="#43A047",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["日期"], y=df["MA_Short"],
        line=dict(color="#FFA726", width=1.5),
        name=f"MA{short_ma}",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["日期"], y=df["MA_Long"],
        line=dict(color="#42A5F5", width=1.5),
        name=f"MA{long_ma}",
    ), row=1, col=1)

    colors = ["#43A047" if v >= 0 else "#E53935" for v in df["涨跌幅"]]
    fig.add_trace(go.Bar(
        x=df["日期"], y=df["成交量"],
        name="成交量", marker_color=colors,
        showlegend=False,
    ), row=2, col=1)

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        height=420, margin=dict(l=20, r=20, t=40, b=20),
        template="plotly_white",
        hovermode="x unified",
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1, font=dict(size=11),
        ),
    )
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig


def render_etf_monitor(all_etfs):
    if not all_etfs:
        st.info("暂无ETF数据，请先完成扫描")
        return

    df = pd.DataFrame(all_etfs)
    buy_count = len(df[df["signal_raw"] == "buy"])
    sell_count = len(df[df["signal_raw"] == "sell"])
    above_count = len(df[df["signal_raw"] == "above"])
    below_count = len(df[df["signal_raw"] == "below"])

    signal_icons = {
        "buy": "🟢 买入信号",
        "sell": "🔴 卖出信号",
        "above": "🟡 金叉区",
        "below": "🔵 死叉区",
    }

    cols = st.columns(4)
    cols[0].metric("🟢 买入信号", f"{buy_count} 只")
    cols[1].metric("🔴 卖出信号", f"{sell_count} 只")
    cols[2].metric("🟡 金叉区", f"{above_count} 只")
    cols[3].metric("🔵 死叉区", f"{below_count} 只")

    filter_col, _ = st.columns([1, 3])
    with filter_col:
        signal_filter = st.selectbox(
            "信号筛选", ["全部", "买入信号 🟢", "卖出信号 🔴", "金叉区 🟡", "死叉区 🔵"],
            label_visibility="collapsed",
        )

    raw_filter = {
        "全部": None,
        "买入信号 🟢": "buy",
        "卖出信号 🔴": "sell",
        "金叉区 🟡": "above",
        "死叉区 🔵": "below",
    }[signal_filter]

    if raw_filter:
        df = df[df["signal_raw"] == raw_filter]
        icon = signal_icons[raw_filter]
        st.caption(f"当前筛选: {icon} 共 {len(df)} 只")
    else:
        st.caption(f"全部ETF: {len(df)} 只")

    if df.empty:
        st.info("当前筛选条件下无数据")
        return

    display_df = df[["代码", "名称", "现价", "涨跌幅", "MA5", "MA10", "signal_raw"]].copy()
    display_df["信号"] = display_df["signal_raw"].map(signal_icons)

    def color_rows(row):
        bg = ""
        if row["signal_raw"] == "buy":
            bg = "background-color: #E8F5E9"
        elif row["signal_raw"] == "sell":
            bg = "background-color: #FFEBEE"
        elif row["signal_raw"] == "above":
            bg = "background-color: #FFF8E1"
        elif row["signal_raw"] == "below":
            bg = "background-color: #E3F2FD"
        return [bg] * len(row)

    styled = display_df.style.apply(color_rows, axis=1)
    styled = styled.format({"现价": "{:.2f}", "MA5": "{:.2f}", "MA10": "{:.2f}"})

    st.dataframe(
        styled,
        column_order=["代码", "名称", "现价", "涨跌幅", "MA5", "MA10", "信号"],
        use_container_width=True,
        hide_index=True,
        height=min(60 + len(display_df) * 38, 600),
    )

    st.subheader("详情查看")
    for _, row in df.iterrows():
        label = f"{signal_icons[row['signal_raw']]} {row['名称']} ({row['代码']}) — ¥{row['现价']}"
        with st.expander(label):
            detail_df = row["_detail_df"]
            if detail_df is not None:
                fig = _build_ma_chart(detail_df, row["名称"], 5, 10)
                st.plotly_chart(fig, use_container_width=True)
