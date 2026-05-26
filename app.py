import io
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from connectors.shopify_connector import load_daily as load_shopify
from connectors.amazon_connector  import load_daily as load_amazon
from connectors.myntra_connector  import load_daily as load_myntra
from connectors.fynd_connector    import load_daily as load_fynd

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="The Pant Project — Sales Dashboard",
    page_icon="👖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="metric-container"] {
    background: #f8f9fb;
    border: 1px solid #e3e6ea;
    border-radius: 10px;
    padding: 16px 20px;
}
[data-testid="stMetricLabel"] { font-size: 13px; color: #666; }
[data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_inr(value: float) -> str:
    v    = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_00_00_000:
        return f"{sign}₹{v / 1_00_00_000:.2f} Cr"
    if v >= 1_00_000:
        return f"{sign}₹{v / 1_00_000:.2f} L"
    return f"{sign}₹{v:,.0f}"


# ── Cached data processing ─────────────────────────────────────────────────────
@st.cache_data(show_spinner="Processing data…")
def process_channels(
    shopify_bytes: bytes,
    amazon_bytes:  bytes,
    myntra_bytes:  bytes,
    fynd_bytes:    bytes,
) -> pd.DataFrame:
    loaders = [
        ("Shopify", load_shopify, shopify_bytes),
        ("Amazon",  load_amazon,  amazon_bytes),
        ("Myntra",  load_myntra,  myntra_bytes),
        ("Fynd",    load_fynd,    fynd_bytes),
    ]
    dfs = []
    for name, loader, raw in loaders:
        try:
            df = loader(io.BytesIO(raw))
            dfs.append(df)
        except Exception as exc:
            st.warning(f"⚠️ Could not process {name}: {exc}")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


@st.cache_data(show_spinner=False)
def process_cogs(cogs_bytes: bytes) -> Optional[pd.DataFrame]:
    df = pd.read_csv(io.BytesIO(cogs_bytes))
    df.columns = df.columns.str.lower().str.strip()
    return df[["sku", "cost_price"]]


# ── Sidebar — file uploaders ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 👖 The Pant Project")
    st.divider()
    st.markdown("### Upload Data")

    shopify_file = st.file_uploader("Shopify CSV",  type="csv", key="shopify")
    amazon_file  = st.file_uploader("Amazon CSV",   type="csv", key="amazon")
    myntra_file  = st.file_uploader("Myntra CSV",   type="csv", key="myntra")
    fynd_file    = st.file_uploader("Fynd CSV",     type="csv", key="fynd")

    st.divider()
    st.markdown("### Gross Margin *(optional)*")
    cogs_file = st.file_uploader("COGS CSV", type="csv", key="cogs",
                                  help="CSV with columns: sku, cost_price")

# ── Upload prompt ──────────────────────────────────────────────────────────────
files_ready = all([shopify_file, amazon_file, myntra_file, fynd_file])

if not files_ready:
    st.title("👖 The Pant Project — Sales Dashboard")
    st.markdown("### Upload your CSV files to get started")
    st.markdown(
        "Use the **sidebar on the left** to upload your four channel exports. "
        "Your data is processed in the browser and never stored anywhere."
    )

    col1, col2 = st.columns(2)
    with col1:
        st.info("**Required files**\n\n"
                "📂 Shopify CSV\n\n"
                "📂 Amazon CSV\n\n"
                "📂 Myntra CSV\n\n"
                "📂 Fynd CSV")
    with col2:
        st.success("**Optional**\n\n"
                   "📂 COGS CSV — enables Gross Margin %\n\n"
                   "Format: two columns\n"
                   "`sku` and `cost_price`")

    uploaded = sum(f is not None for f in [shopify_file, amazon_file, myntra_file, fynd_file])
    if uploaded > 0:
        st.progress(uploaded / 4, text=f"{uploaded} of 4 files uploaded")
    st.stop()

# ── Process uploaded files ─────────────────────────────────────────────────────
df_raw = process_channels(
    shopify_file.read(), amazon_file.read(),
    myntra_file.read(),  fynd_file.read(),
)

cogs_df  = process_cogs(cogs_file.read()) if cogs_file else None
has_cogs = cogs_df is not None

if df_raw.empty:
    st.error("No data could be loaded. Check that the correct CSV files were uploaded.")
    st.stop()

df_raw["date"] = pd.to_datetime(df_raw["date"])

# ── Sidebar — filters (shown after upload) ─────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("### Filters")

    min_d = df_raw["date"].min().date()
    max_d = df_raw["date"].max().date()

    date_range = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
    )

    all_channels = sorted(df_raw["channel"].unique())
    channels = st.multiselect("Channels", options=all_channels, default=all_channels)

    st.divider()
    st.caption(f"Data: {min_d.strftime('%d %b %Y')} → {max_d.strftime('%d %b %Y')}")
    if not has_cogs:
        st.info("💡 Upload `cogs.csv` above to unlock **Gross Margin %**")

# ── Apply filters ──────────────────────────────────────────────────────────────
if len(date_range) == 2:
    s, e = date_range
    df = df_raw[
        (df_raw["date"].dt.date >= s) &
        (df_raw["date"].dt.date <= e) &
        (df_raw["channel"].isin(channels))
    ].copy()
else:
    df = df_raw[df_raw["channel"].isin(channels)].copy()

if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

# ── Merge COGS ─────────────────────────────────────────────────────────────────
if has_cogs:
    df = df.merge(cogs_df, on="sku", how="left")
    df["total_cogs"] = df["units_sold"] * df["cost_price"].fillna(0)
else:
    df["total_cogs"] = 0.0

# ── KPI calculations ───────────────────────────────────────────────────────────
gross_rev    = df["gross_sales"].sum()
net_rev      = df["net_sales"].sum()
gross_profit = net_rev - df["total_cogs"].sum()
gm_pct       = gross_profit / net_rev * 100 if net_rev else 0
units        = int(df["units_sold"].sum())
total_ret    = abs(df["returns"].sum())
total_disc   = abs(df["discounts"].sum())
total_orders = df["orders"].sum()
return_rate  = total_ret / gross_rev * 100 if gross_rev else 0
aov          = net_rev / total_orders if total_orders else 0

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("👖 The Pant Project — Sales Dashboard")
if len(date_range) == 2:
    st.caption(
        f"📅 **{date_range[0].strftime('%d %b %Y')}** → **{date_range[1].strftime('%d %b %Y')}**"
        f"  ·  Channels: {', '.join(channels)}"
    )

# ── KPI row 1 ──────────────────────────────────────────────────────────────────
st.markdown("#### Revenue & Margin")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Gross Revenue",  fmt_inr(gross_rev))
c2.metric("Net Revenue",    fmt_inr(net_rev))
c3.metric("Gross Margin %", f"{gm_pct:.1f}%" if has_cogs else "— upload cogs.csv")
c4.metric("Units Sold",     f"{units:,}")

# ── KPI row 2 ──────────────────────────────────────────────────────────────────
st.markdown("#### Deductions & Orders")
c5, c6, c7, c8 = st.columns(4)
c5.metric("Total Discounts", fmt_inr(total_disc))
c6.metric("Total Returns",   fmt_inr(total_ret))
c7.metric("Return Rate",     f"{return_rate:.1f}%")
c8.metric("Avg Order Value", fmt_inr(aov))

st.divider()

# ── Revenue trend + channel split ──────────────────────────────────────────────
col_l, col_r = st.columns([3, 2])

with col_l:
    daily_ch = (
        df.groupby(["date", "channel"])
        .agg(net_sales=("net_sales", "sum"))
        .reset_index()
    )
    fig_trend = px.line(
        daily_ch, x="date", y="net_sales", color="channel",
        title="Daily Net Revenue by Channel",
        labels={"net_sales": "Net Revenue (₹)", "date": "Date", "channel": "Channel"},
        template="plotly_white",
    )
    fig_trend.update_traces(line=dict(width=2.5))
    fig_trend.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    st.plotly_chart(fig_trend, use_container_width=True)

with col_r:
    ch_rev  = df.groupby("channel")["net_sales"].sum().reset_index()
    fig_pie = px.pie(
        ch_rev, values="net_sales", names="channel",
        title="Net Revenue Split by Channel",
        hole=0.45, template="plotly_white",
    )
    fig_pie.update_traces(textposition="outside", textinfo="percent+label")
    fig_pie.update_layout(showlegend=False)
    st.plotly_chart(fig_pie, use_container_width=True)

# ── Channel comparison ─────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    ch_units  = df.groupby("channel")["units_sold"].sum().reset_index()
    fig_units = px.bar(
        ch_units, x="channel", y="units_sold", color="channel",
        title="Units Sold by Channel",
        labels={"units_sold": "Units Sold", "channel": "Channel"},
        template="plotly_white", text="units_sold",
    )
    fig_units.update_traces(textposition="outside")
    fig_units.update_layout(showlegend=False)
    st.plotly_chart(fig_units, use_container_width=True)

with col_b:
    if has_cogs:
        ch_gm = (
            df.groupby("channel")
            .agg(net_s=("net_sales", "sum"), cogs=("total_cogs", "sum"))
            .reset_index()
        )
        ch_gm["gm_pct"] = ((ch_gm["net_s"] - ch_gm["cogs"]) / ch_gm["net_s"] * 100).round(1)
        fig_gm = px.bar(
            ch_gm, x="channel", y="gm_pct", color="channel",
            title="Gross Margin % by Channel",
            labels={"gm_pct": "Gross Margin %", "channel": "Channel"},
            template="plotly_white",
            text=ch_gm["gm_pct"].astype(str) + "%",
        )
        fig_gm.update_traces(textposition="outside")
        fig_gm.update_layout(showlegend=False, yaxis_range=[0, 100])
        st.plotly_chart(fig_gm, use_container_width=True)
    else:
        ret_ch = df.groupby("channel")[["gross_sales", "returns"]].sum().reset_index()
        ret_ch["return_rate"] = (abs(ret_ch["returns"]) / ret_ch["gross_sales"] * 100).round(1)
        fig_ret = px.bar(
            ret_ch, x="channel", y="return_rate", color="channel",
            title="Return Rate % by Channel",
            labels={"return_rate": "Return Rate %", "channel": "Channel"},
            template="plotly_white",
            text=ret_ch["return_rate"].astype(str) + "%",
        )
        fig_ret.update_traces(textposition="outside")
        fig_ret.update_layout(showlegend=False)
        st.plotly_chart(fig_ret, use_container_width=True)

st.divider()

# ── SKU Analysis ───────────────────────────────────────────────────────────────
st.markdown("#### Top SKUs")
tab_rev, tab_units = st.tabs(["By Net Revenue", "By Units Sold"])

with tab_rev:
    top_rev = (
        df.groupby("sku")["net_sales"].sum()
        .reset_index().sort_values("net_sales", ascending=True).tail(20)
    )
    fig_skurev = px.bar(
        top_rev, x="net_sales", y="sku", orientation="h",
        title="Top 20 SKUs — Net Revenue",
        labels={"net_sales": "Net Revenue (₹)", "sku": "SKU"},
        template="plotly_white", color="net_sales",
        color_continuous_scale="Blues",
    )
    fig_skurev.update_layout(coloraxis_showscale=False, height=580)
    st.plotly_chart(fig_skurev, use_container_width=True)

with tab_units:
    top_units = (
        df.groupby("sku")["units_sold"].sum()
        .reset_index().sort_values("units_sold", ascending=True).tail(20)
    )
    fig_skuunits = px.bar(
        top_units, x="units_sold", y="sku", orientation="h",
        title="Top 20 SKUs — Units Sold",
        labels={"units_sold": "Units Sold", "sku": "SKU"},
        template="plotly_white", color="units_sold",
        color_continuous_scale="Greens",
    )
    fig_skuunits.update_layout(coloraxis_showscale=False, height=580)
    st.plotly_chart(fig_skuunits, use_container_width=True)

st.divider()

# ── Raw data table ─────────────────────────────────────────────────────────────
with st.expander("📋 View & Download Raw Data"):
    display_df = df.drop(columns=["total_cogs", "cost_price"], errors="ignore")
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Download filtered data as CSV",
        data=display_df.to_csv(index=False).encode("utf-8"),
        file_name="pant_project_sales_filtered.csv",
        mime="text/csv",
    )
