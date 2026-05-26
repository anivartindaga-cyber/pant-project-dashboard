import io
import pandas as pd

CHANNEL = "Shopify"


def _read_file(source, **kwargs):
    if hasattr(source, "read"):
        raw  = source.read()
        text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
        df   = pd.read_csv(io.StringIO(text), **kwargs)
    else:
        df = pd.read_csv(source, encoding="utf-8-sig", **kwargs)
    df.columns = df.columns.str.strip().str.lstrip("﻿")
    return df


def load_daily(source) -> pd.DataFrame:
    df = _read_file(source)
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
    result["channel"] = CHANNEL
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]
