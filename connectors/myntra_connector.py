from pathlib import Path
import pandas as pd

CHANNEL = "Myntra"
CSV_PATH = Path(__file__).parent.parent / "data" / "myntra_export.csv"

DELIVERED_STATUSES = {"C", "D"}
RETURN_STATUSES    = {"RTO", "RTF"}


def load_daily() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, low_memory=False)

    # Myntra exports often lose the date portion of timestamps (CSV formatting
    # issue). We fall back across multiple columns to find the best date.
    df["_date"] = pd.NaT
    for col in ["return creation date", "rto creation date",
                "delivered on", "cancelled on", "created on"]:
        if col in df.columns:
            df["_date"] = df["_date"].combine_first(
                pd.to_datetime(df[col], errors="coerce")
            )

    df["date"] = df["_date"].dt.normalize()

    key      = ["date", "seller sku code"]
    sales_df = df[df["order status"].isin(DELIVERED_STATUSES)].copy()
    ret_df   = df[df["order status"].isin(RETURN_STATUSES)].copy()

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
    agg_sales["discounts"] = -agg_sales["discounts"]  # make negative to match convention

    agg_returns = (
        ret_df.groupby(key)
        .agg(returns=("seller price", "sum"))
        .reset_index()
    )
    agg_returns["returns"] = -agg_returns["returns"]  # negative = revenue lost

    result = agg_sales.merge(agg_returns, on=key, how="left")
    result["returns"] = result["returns"].fillna(0)

    result = result.rename(columns={"seller sku code": "sku"})
    result["channel"] = CHANNEL
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]
