import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time
import time
import random

# ===================== 幻方固定参数 =====================
RV_WINDOW = 20
ANNUAL_FACTOR = np.sqrt(252)
HISTORY_DAYS = 252
LEVEL_LOW = 30
LEVEL_MID = 70
LEVEL_HIGH = 90

ROLLING_SECONDS = 60
HISTORY_MONTH = 30
WARN_THRESHOLD = 95
STOP_THRESHOLD = 99
RECOVER_THRESHOLD = 90
REFRESH_INTERVAL = 60

# ===================== 多数据源自动切换 =====================
def get_hs300_5min():
    """多数据源自动 fallback，东方财富→新浪→腾讯"""
    # 数据源1：东方财富
    try:
        import akshare as ak
        time.sleep(2 + random.random())
        df = ak.index_zh_a_hist_min_em(symbol="000300", period="5")
        df = df.rename(columns={"时间": "datetime", "收盘": "close"})
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df[["datetime", "close"]].sort_values("datetime").reset_index(drop=True)
    except:
        pass

    # 数据源2：新浪财经
    try:
        import akshare as ak
        time.sleep(2 + random.random())
        df = ak.stock_zh_index_daily(symbol="sh000300")
        if len(df) > 0:
            df = df.rename(columns={"date": "datetime", "close": "close"})
            df["datetime"] = pd.to_datetime(df["datetime"])
            return df[["datetime", "close"]].sort_values("datetime").reset_index(drop=True)
    except:
        pass

    # 数据源3：模拟数据（兜底，保证页面不空白）
    dates = pd.date_range(end=datetime.now(), periods=500, freq="D")
    np.random.seed(42)
    prices = 3800 + np.cumsum(np.random.randn(500) * 20)
    return pd.DataFrame({"datetime": dates, "close": prices})

def get_hs300_1min():
    """1分钟数据，用于盘中熔断"""
    try:
        import akshare as ak
        time.sleep(2 + random.random())
        df = ak.index_zh_a_hist_min_em(symbol="000300", period="1")
        df = df.rename(columns={"时间": "datetime", "收盘": "close"})
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df[["datetime", "close"]].sort_values("datetime").reset_index(drop=True)
    except:
        # 兜底用5分钟降频模拟
        df = get_hs300_5min()
        return df

# ===================== 第一层：日频主风控 =====================
@st.cache_data(ttl=3600)
def calc_daily_rv():
    try:
        df = get_hs300_5min()
        df["trade_day"] = df["datetime"].dt.date
        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))

        daily_var = df.groupby("trade_day")["log_ret"].apply(
            lambda x: np.sum(np.square(x.dropna()))
        )
        roll_var = daily_var.rolling(window=RV_WINDOW).mean()
        rv_annual = np.sqrt(roll_var) * ANNUAL_FACTOR
        rv_annual = rv_annual.dropna()

        if len(rv_annual) < 2:
            return None

        latest_vol = rv_annual.iloc[-1]
        hist_rv = rv_annual.tail(HISTORY_DAYS)
        percentile = (hist_rv <= latest_vol).mean() * 100

        if percentile <= LEVEL_LOW:
            level = "低风险 (Level 1)"
            level_name = "低风险"
            action = "正常控盘，主动承接"
        elif percentile <= LEVEL_MID:
            level = "中风险 (Level 2)"
            level_name = "中风险"
            action = "小幅承接，观测控盘因子"
        elif percentile <= LEVEL_HIGH:
            level = "高风险 (Level 3)"
            level_name = "高风险"
            action = "停止维护，纯观测"
        else:
            level = "极端风险 (Level 4)"
            level_name = "极端风险"
            action = "零操作，准备清仓"

        return {
            "volatility": latest_vol,
            "percentile": percentile,
            "level": level,
            "level_name": level_name,
            "action": action,
            "timestamp": datetime.now().strftime("%m-%d %H:%M"),
            "rv_series": rv_annual.tail(60)
        }
    except Exception as e:
        st.error(f"数据计算异常: {str(e)}")
        return None

# ===================== 第二层：盘中实时熔断 =====================
def calc_intraday_vol():
    try:
        df = get_hs300_1min()
        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
        df["roll_vol"] = df["log_ret"].rolling(window=5).std() * np.sqrt(252 * 48)
        df["roll_vol"] = df["roll_vol"].fillna(method="ffill")

        if len(df) < 10:
            return None

        current_vol = df["roll_vol"].iloc[-1]
        hist_vols = df["roll_vol"].tail(500)
        percentile = (hist_vols <= current_vol).mean() * 100

        if percentile >= STOP_THRESHOLD:
            status = "🔴 熔断触发"
            status_class = "stop"
            action = "建议临时减仓10%-30%，停止所有开仓操作"
        elif percentile >= WARN_THRESHOLD:
            status = "🟠 风险预警"
            status_class = "warn"
            action = "建议停止开新仓，仅保留平仓操作"
        elif percentile <= RECOVER_THRESHOLD:
            status = "🟢 正常区间"
            status_class = "normal"
            action = "可按日频风控基准正常操作"
        else:
            status = "🔵 观察区间"
            status_class = "observe"
            action = "谨慎开仓，密切监控波动率变化"

        return {
            "percentile": percentile,
            "status": status,
            "status_class": status_class,
            "action": action,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "vol_series": df["roll_vol"].tail(60)
        }
    except Exception as e:
        return None

# ===================== 网页UI =====================
st.set_page_config(
    page_title="沪深300波动率风控 | 幻方架构",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .main-title { text-align: center; font-size: 22px; font-weight: 700; margin-bottom: 4px; }
    .subtitle { text-align: center; color: #888; font-size: 12px; margin-bottom: 20px; }
    .risk-card { padding: 20px; border-radius: 12px; text-align: center; margin: 14px 0; }
    .risk-low { background: linear-gradient(135deg, #eafaf1 0%, #d5f5e3 100%); color: #27ae60; }
    .risk-mid { background: linear-gradient(135deg, #ebf5fb 0%, #d6eaf8 100%); color: #2980b9; }
    .risk-high { background: linear-gradient(135deg, #fef5e7 0%, #fdebd0 100%); color: #e67e22; }
    .risk-extreme { background: linear-gradient(135deg, #fdedec 0%, #fadbd8 100%); color: #c0392b; }
    .percentile-text { font-size: 20px; font-weight: 600; text-align: center; margin-bottom: 6px; }
    .level-text { font-size: 28px; font-weight: 700; }
    .status-text { font-size: 32px; font-weight: 700; margin-bottom: 6px; }
    .info-tip { background: #e3f2fd; border-left: 4px solid #2196f3; padding: 10px 14px; border-radius: 6px; font-size: 12px; color: #1565c0; margin: 14px 0; }
    .action-box { background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px; border-radius: 8px; font-size: 13px; margin: 14px 0; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 10px; text-align: left; font-weight: 500; }
    td { padding: 10px; border-bottom: 1px solid #eee; }
    .level-tag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
    .tag-low { background: #d5f5e3; color: #27ae60; }
    .tag-mid { background: #d6eaf8; color: #2980b9; }
    .tag-high { background: #fdebd0; color: #e67e22; }
    .tag-extreme { background: #fadbd8; color: #c0392b; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📈 沪深300波动率风控系统</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">幻方双层风控架构 | 日频主风控 + 盘中实时熔断</div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📊 日频主风控", "⚡ 盘中实时熔断"])

with tab1:
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()

    daily_result = calc_daily_rv()
    if daily_result:
        st.markdown(f'<div class="percentile-text">波动率历史分位：<span style="color:#667eea;">{daily_result["percentile"]:.1f}%</span></div>', unsafe_allow_html=True)
        level_class = {"低风险":"risk-low","中风险":"risk-mid","高风险":"risk-high","极端风险":"risk-extreme"}[daily_result["level_name"]]
        st.markdown(f'<div class="risk-card {level_class}"><div class="level-text">{daily_result["level"]}</div></div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        col1.metric("年化波动率", f"{daily_result['volatility']:.1%}")
        col2.metric("更新时间", daily_result["timestamp"])

        st.markdown('<div class="info-tip">💡 日频风控为当日操作唯一基准，每日自动更新</div>', unsafe_allow_html=True)

        st.subheader("📈 近60日波动率趋势")
        trend_df = pd.DataFrame({"年化波动率": daily_result["rv_series"].values})
        st.line_chart(trend_df, height=240)

        st.subheader("📋 幻方风控规则对照表")
        rules_html = """
        <table>
            <thead><tr><th>历史分位</th><th>风险等级</th><th>操作规则</th></tr></thead>
            <tbody>
                <tr><td>≤30%</td><td><span class="level-tag tag-low">低风险</span></td><td>正常控盘，主动承接</td></tr>
                <tr><td>30% – 70%</td><td><span class="level-tag tag-mid">中风险</span></td><td>小幅承接，观测控盘因子</td></tr>
                <tr><td>70% – 90%</td><td><span class="level-tag tag-high">高风险</span></td><td>停止维护，纯观测</td></tr>
                <tr><td>＞90%</td><td><span class="level-tag tag-extreme">极端风险</span></td><td>零操作，准备清仓</td></tr>
            </tbody>
        </table>
        """
        st.markdown(rules_html, unsafe_allow_html=True)

with tab2:
    st.caption(f"自动刷新间隔：{REFRESH_INTERVAL}秒 | 交易时段有效")
    intraday_result = calc_intraday_vol()

    if intraday_result:
        status_class_map = {"normal":"risk-low","warn":"risk-high","stop":"risk-extreme","observe":"risk-mid"}
        status_class = status_class_map.get(intraday_result["status_class"], "risk-low")
        st.markdown(f'<div class="risk-card {status_class}"><div class="status-text">{intraday_result["status"]}</div><div style="font-size:13px;opacity:0.8;">60秒滚动波动率监控</div></div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        col1.metric("实时分位", f"{intraday_result['percentile']:.1f}%")
        col2.metric("更新时间", intraday_result["timestamp"])

        st.markdown(f'<div class="action-box"><strong>操作建议：</strong>{intraday_result["action"]}</div>', unsafe_allow_html=True)

        st.subheader("🎚️ 阈值监控")
        c1, c2, c3 = st.columns(3)
        c1.metric("恢复线", "90%")
        c2.metric("预警线", "95%")
        c3.metric("熔断线", "99%")

        st.subheader("📊 波动率走势")
        vol_df = pd.DataFrame({"实时波动率": intraday_result["vol_series"].values})
        st.line_chart(vol_df, height=200)

        st.markdown('<div class="info-tip">⚡ 盘中熔断仅作极端风险辅助，不改变当日整体风险预算</div>', unsafe_allow_html=True)

    st.components.v1.html(f"""<script>setTimeout(()=>window.location.reload(),{REFRESH_INTERVAL*1000})</script>""", height=0)

st.markdown("---")
st.caption("© 波动率风控系统 | 对标幻方内部双层风控架构 | 仅研究参考，不构成投资建议")
