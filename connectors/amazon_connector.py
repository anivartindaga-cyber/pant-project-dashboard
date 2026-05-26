import pandas as pd

CHANNEL = "Amazon"
SKIPROWS = 14  # metadata rows before the actual header


def load_daily(source) -> pd.DataFrame:
    """source: a file path, file-like object, or BytesIO from st.file_uploader."""
    df = pd.read_csv(source, skiprows=SKIPROWS, thousands=",")

    df["date"] = pd.to_datetime(
        df["date/time"].astype(str).str.replace(r"\s+UTC$", "", regex=True),
        format="%d %b %Y %I:%M:%S %p",
        errors="coerce",
    ).dt.normalize()

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
    result["channel"] = CHANNEL
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]
