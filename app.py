import io
import re
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="The Pant Project — Sales Dashboard",
    page_icon="\U0001f456",
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


# ══════════════════════════════════════════════════════════════════════════════
# CHANNEL CONNECTORS  (inlined — no separate package required)
# ══════════════════════════════════════════════════════════════════════════════

def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and BOM from column names."""
    df.columns = df.columns.str.strip().str.lstrip("﻿")
    return df


def _read_csv_generic(source, **kwargs) -> pd.DataFrame:
    if hasattr(source, "read"):
        raw  = source.read()
        text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
        df   = pd.read_csv(io.StringIO(text), **kwargs)
    else:
        df = pd.read_csv(source, encoding="utf-8-sig", **kwargs)
    return _clean_cols(df)


# ── Shopify ───────────────────────────────────────────────────────────────────
def load_shopify(source) -> pd.DataFrame:
    df = _read_csv_generic(source)
    df["date"] = pd.to_datetime(df["Day"], format="%m/%d/%Y")
    result = (
        df.groupby(["date", "Product variant SKU"])
        .agg(
            orders=("Orders", "sum"),
            gross_sales=("Gross sales", "sum"),
            discounts=("Discounts", "sum"),
            returns=("Returns", "sum"),
            net_sales=("Net sales", "sum"),
            units_sold=("Net items sold", "sum"),
        )
        .reset_index()
        .rename(columns={"Product variant SKU": "sku"})
    )
    result["channel"] = "TPP Website"
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]


# ── Amazon ────────────────────────────────────────────────────────────────────
def _read_amazon_csv(source) -> pd.DataFrame:
    if hasattr(source, "read"):
        raw  = source.read()
        text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    else:
        with open(source, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()

    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines)
         if line.lstrip("﻿").lower().startswith("date/time")),
        None,
    )
    if header_idx is None:
        raise ValueError("Could not find 'date/time' header row in Amazon CSV.")
    return _clean_cols(
        pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), thousands=",")
    )


def load_amazon(source) -> pd.DataFrame:
    df = _read_amazon_csv(source)

    df["date"] = pd.to_datetime(
        df["date/time"].astype(str).str.extract(r"(\d{1,2} \w{3} \d{4})")[0],
        format="%d %b %Y",
        errors="coerce",
    )

    for col in ["product sales", "total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            ).fillna(0)

    df = df[df["date"].notna() & df["type"].isin(["Order", "Refund"])].copy()

    key     = ["date", "Sku"]
    orders  = df[df["type"] == "Order"]
    refunds = df[df["type"] == "Refund"]

    agg_orders = (
        orders.groupby(key)
        .agg(
            orders=("quantity", "sum"),
            units_sold=("quantity", "sum"),
            gross_sales=("product sales", "sum"),
            net_sales=("total", "sum"),
        )
        .reset_index()
    )
    agg_refunds = (
        refunds.groupby(key)
        .agg(returns=("product sales", "sum"))
        .reset_index()
    )

    result = agg_orders.merge(agg_refunds, on=key, how="left")
    result["returns"]   = result["returns"].fillna(0)
    result["discounts"] = 0.0

    result = result.rename(columns={"Sku": "sku"})
    result["channel"] = "Amazon"
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]


# ── Myntra ────────────────────────────────────────────────────────────────────
_MYNTRA_DELIVERED = {"C", "D"}
_MYNTRA_RETURNS   = {"RTO", "RTF"}


def load_myntra(source) -> pd.DataFrame:
    df = _read_csv_generic(source, low_memory=False)

    df["_date"] = pd.NaT
    for col in ["return creation date", "rto creation date",
                "delivered on", "cancelled on", "created on"]:
        if col in df.columns:
            df["_date"] = df["_date"].combine_first(
                pd.to_datetime(df[col], errors="coerce")
            )
    df["date"] = df["_date"].dt.normalize()

    key      = ["date", "seller sku code"]
    sales_df = df[df["order status"].isin(_MYNTRA_DELIVERED)].copy()
    ret_df   = df[df["order status"].isin(_MYNTRA_RETURNS)].copy()

    agg_sales = (
        sales_df.groupby(key)
        .agg(
            orders=("order release id", "count"),
            gross_sales=("final amount", "sum"),
            discounts=("discount", "sum"),
            net_sales=("seller price", "sum"),
            units_sold=("order release id", "count"),
        )
        .reset_index()
    )
    agg_sales["discounts"] = -agg_sales["discounts"]

    agg_returns = (
        ret_df.groupby(key)
        .agg(returns=("seller price", "sum"))
        .reset_index()
    )
    agg_returns["returns"] = -agg_returns["returns"]

    result = agg_sales.merge(agg_returns, on=key, how="left")
    result["returns"] = result["returns"].fillna(0)

    result = result.rename(columns={"seller sku code": "sku"})
    result["channel"] = "Myntra"
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]


# ── Fynd ──────────────────────────────────────────────────────────────────────
def load_fynd(source) -> pd.DataFrame:
    df = _read_csv_generic(source)
    df["date"] = pd.to_datetime(df["Day"], format="%Y-%m-%d")

    result = (
        df.groupby(["date", "Product variant SKU"])
        .agg(
            orders=("Orders", "sum"),
            gross_sales=("Gross sales", "sum"),
            discounts=("Discounts", "sum"),
            returns=("Returns", "sum"),
            net_sales=("Net sales", "sum"),
            units_sold=("Net items sold", "sum"),
        )
        .reset_index()
        .rename(columns={"Product variant SKU": "sku"})
    )
    result["channel"] = "Retail"
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_inr(value: float) -> str:
    v    = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_00_00_000:
        return f"{sign}₹{v / 1_00_00_000:.2f} Cr"
    if v >= 1_00_000:
        return f"{sign}₹{v / 1_00_000:.2f} L"
    return f"{sign}₹{v:,.0f}"


# ══════════════════════════════════════════════════════════════════════════════
# CACHED DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

# Standard output columns produced by every loader
_OUT_COLS  = ["channel", "date", "sku", "orders", "gross_sales",
              "discounts", "returns", "net_sales", "units_sold"]
_OUT_SET   = set(_OUT_COLS) - {"date"}   # date may be named differently


def _try_passthrough(raw: bytes) -> Optional[pd.DataFrame]:
    """
    If the CSV is already in processed form (has our standard columns),
    load it directly rather than pushing it through a raw-export parser.
    Returns a DataFrame or None.
    """
    try:
        peek = pd.read_csv(io.BytesIO(raw), nrows=0)
        peek.columns = peek.columns.str.strip().str.lower()
        if _OUT_SET.issubset(set(peek.columns)):
            df = pd.read_csv(io.BytesIO(raw))
            df.columns = df.columns.str.strip().str.lower()
            # Handle date/month column
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            elif "month" in df.columns:
                df["date"] = pd.to_datetime(df["month"], errors="coerce")
                df = df.drop(columns=["month"])
            else:
                df["date"] = pd.Timestamp.today().normalize()
            return df[_OUT_COLS]
    except Exception:
        pass
    return None


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
    dfs        = []
    seen_hashes: set = set()   # avoid loading the same file twice

    for name, loader, raw in loaders:
        file_hash = hash(raw)

        # ── Already-processed CSV? ──────────────────────────────────────────
        pt = _try_passthrough(raw)
        if pt is not None:
            if file_hash not in seen_hashes:
                seen_hashes.add(file_hash)
                dfs.append(pt)
                st.info(
                    f"ℹ️ **{name}**: detected a pre-processed CSV — loaded directly. "
                    "If you meant to upload the raw platform export, re-upload the "
                    "original file downloaded from the platform."
                )
            continue

        # ── Raw channel export ──────────────────────────────────────────────
        if file_hash in seen_hashes:
            continue
        seen_hashes.add(file_hash)

        try:
            df = loader(io.BytesIO(raw))
            dfs.append(df)
        except Exception as exc:
            try:
                peek = pd.read_csv(io.BytesIO(raw), nrows=0)
                cols = list(peek.columns)
            except Exception:
                cols = ["could not read columns"]
            st.warning(
                f"⚠️ Could not process {name}: {exc}  |  Columns found: {cols}"
            )

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def _base_style(sku: str) -> str:
    """Strip trailing size suffix: -32, _34, -XL, _XXL, -L, _S etc."""
    return re.sub(r'[-_](\d{2,3}|XXL|XL|XS|XXXL|[LMSX])$', '', str(sku).strip())


def compute_fifo_cogs(sales_df: pd.DataFrame, purchases_df: pd.DataFrame) -> pd.Series:
    """
    FIFO costing: consume oldest purchase batches first as sales occur.
    Optimised: vectorised style-key computation, itertuples, pre-built last_cost dict.
    """
    from collections import deque

    _SIZE_RE = r'[-_](\d{2,3}|XXXL|XXL|XL|XS|[LMSX])$'

    # Vectorised style-key stripping (much faster than per-row apply)
    pur = purchases_df.copy()
    pur["sk"] = pur["sku"].astype(str).str.strip().str.replace(_SIZE_RE, '', regex=True)
    pur = pur.sort_values("date")

    queues:    dict = {}
    last_cost: dict = {}          # fallback cost when stock runs out
    for row in pur.itertuples(index=False):
        sk = row.sk
        if sk not in queues:
            queues[sk] = deque()
        queues[sk].append([float(row.quantity), float(row.cost_price)])
        last_cost[sk] = float(row.cost_price)

    sal = sales_df.copy()
    sal["sk"] = sal["sku"].astype(str).str.strip().str.replace(_SIZE_RE, '', regex=True)
    sal = sal.sort_values("date")

    result: dict = {}
    for row in sal.itertuples():
        sk        = row.sk
        remaining = max(0.0, float(row.units_sold))
        cogs      = 0.0

        q = queues.get(sk)
        if q:
            while remaining > 0 and q:
                batch     = q[0]
                take      = min(remaining, batch[0])
                cogs     += take * batch[1]
                remaining -= take
                batch[0]  -= take
                if batch[0] == 0:
                    q.popleft()

        if remaining > 0:
            cogs += remaining * last_cost.get(sk, 0.0)

        result[row.Index] = cogs

    return pd.Series(result, dtype=float).reindex(sales_df.index).fillna(0.0)


@st.cache_data(show_spinner="Calculating FIFO costs…")
def _cached_fifo(sales_df: pd.DataFrame, purchases_df: pd.DataFrame) -> pd.Series:
    """Cached wrapper so FIFO only reruns when data actually changes."""
    return compute_fifo_cogs(sales_df, purchases_df)


@st.cache_data(show_spinner=False)
def process_cogs(cogs_bytes: bytes):
    """
    Returns (mode, df) where mode is 'fifo' or 'flat'.
    FIFO mode: CSV has columns date, sku, quantity, cost_price.
    Flat mode: CSV has columns sku, cost_price (one row per style).
    """
    df = pd.read_csv(io.BytesIO(cogs_bytes))
    df.columns = df.columns.str.lower().str.strip()

    if "date" in df.columns and "quantity" in df.columns:
        df["date"]       = pd.to_datetime(df["date"], errors="coerce")
        df["quantity"]   = pd.to_numeric(df["quantity"],   errors="coerce").fillna(0)
        df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce").fillna(0)
        return ("fifo", df[["date", "sku", "quantity", "cost_price"]])
    else:
        if "style_code" in df.columns:
            df = df.rename(columns={"style_code": "sku"})
        df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce")
        return ("flat", df[["sku", "cost_price"]])


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — FILE UPLOADERS
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## \U0001f456 The Pant Project")
    st.divider()
    st.markdown("### Upload Data")

    shopify_file = st.file_uploader("TPP Website CSV", type="csv", key="shopify")
    amazon_file  = st.file_uploader("Amazon CSV",      type="csv", key="amazon")
    myntra_file  = st.file_uploader("Myntra CSV",      type="csv", key="myntra")
    fynd_file    = st.file_uploader("Retail CSV",      type="csv", key="fynd")

    st.divider()
    st.markdown("### Gross Margin *(optional)*")
    cogs_file = st.file_uploader("Purchases / COGS CSV", type="csv", key="cogs",
                                  help=(
                                      "FIFO mode — columns: date, sku, quantity, cost_price\n"
                                      "Flat mode  — columns: sku, cost_price"
                                  ))

# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD PROMPT
# ══════════════════════════════════════════════════════════════════════════════

files_ready = all([shopify_file, amazon_file, myntra_file, fynd_file])

if not files_ready:
    st.title("\U0001f456 The Pant Project — Sales Dashboard")
    st.markdown("### Upload your CSV files to get started")
    st.markdown(
        "Use the **sidebar on the left** to upload your four channel exports. "
        "Your data is processed in the browser and never stored anywhere."
    )

    col1, col2 = st.columns(2)
    with col1:
        st.info("**Required files**\n\n"
                "\U0001f4c2 TPP Website CSV\n\n"
                "\U0001f4c2 Amazon CSV\n\n"
                "\U0001f4c2 Myntra CSV\n\n"
                "\U0001f4c2 Retail CSV")
    with col2:
        st.success("**Optional**\n\n"
                   "\U0001f4c2 Purchases CSV — enables Gross Margin %\n\n"
                   "**FIFO:** `date, sku, quantity, cost_price`\n\n"
                   "**Flat:** `sku, cost_price`")

    uploaded = sum(f is not None for f in [shopify_file, amazon_file, myntra_file, fynd_file])
    if uploaded > 0:
        st.progress(uploaded / 4, text=f"{uploaded} of 4 files uploaded")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# PROCESS UPLOADED FILES
# ══════════════════════════════════════════════════════════════════════════════

df_raw = process_channels(
    shopify_file.read(), amazon_file.read(),
    myntra_file.read(),  fynd_file.read(),
)

_cogs_result = process_cogs(cogs_file.read()) if cogs_file else None
has_cogs     = _cogs_result is not None
cogs_mode    = _cogs_result[0] if has_cogs else None
cogs_df      = _cogs_result[1] if has_cogs else None

if df_raw.empty:
    st.error("No data could be loaded. Check that the correct CSV files were uploaded.")
    st.stop()

df_raw["date"] = pd.to_datetime(df_raw["date"])

# Normalise legacy channel names
df_raw["channel"] = df_raw["channel"].replace({
    "Shopify": "TPP Website",
    "Fynd":    "Retail",
})

# ── Compute COGS on full dataset (FIFO needs all history before filtering) ──
if has_cogs:
    if cogs_mode == "fifo":
        df_raw["total_cogs"] = _cached_fifo(df_raw, cogs_df)
    else:
        df_raw = df_raw.merge(cogs_df, on="sku", how="left")
        no_match = df_raw["cost_price"].isna()
        if no_match.any():
            style_map = dict(zip(
                cogs_df["sku"].apply(_base_style),
                cogs_df["cost_price"]
            ))
            df_raw.loc[no_match, "cost_price"] = (
                df_raw.loc[no_match, "sku"].apply(_base_style).map(style_map)
            )
        df_raw["total_cogs"] = df_raw["units_sold"] * df_raw["cost_price"].fillna(0)
else:
    df_raw["total_cogs"] = 0.0

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — FILTERS
# ══════════════════════════════════════════════════════════════════════════════

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
        st.info("\U0001f4a1 Upload a purchases CSV above to unlock **Gross Margin %**")

# ══════════════════════════════════════════════════════════════════════════════
# APPLY FILTERS
# ══════════════════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════════════════
# KPI CALCULATIONS
# ══════════════════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

st.title("\U0001f456 The Pant Project — Sales Dashboard")
if len(date_range) == 2:
    st.caption(
        f"\U0001f4c5 **{date_range[0].strftime('%d %b %Y')}** → **{date_range[1].strftime('%d %b %Y')}**"
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

# ── Revenue trend + channel split ─────────────────────────────────────────────
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
        ch_gm["gm_pct"] = (
            (ch_gm["net_s"] - ch_gm["cogs"]) / ch_gm["net_s"] * 100
        ).round(1)
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
        ret_ch["return_rate"] = (
            abs(ret_ch["returns"]) / ret_ch["gross_sales"] * 100
        ).round(1)
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

# ── Top SKUs ──────────────────────────────────────────────────────────────────
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
with st.expander("\U0001f4cb View & Download Raw Data"):
    display_df = df.drop(columns=["total_cogs", "cost_price"], errors="ignore")
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Download filtered data as CSV",
        data=display_df.to_csv(index=False).encode("utf-8"),
        file_name="pant_project_sales_filtered.csv",
        mime="text/csv",
    )
