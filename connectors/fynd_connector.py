from pathlib import Path
import pandas as pd

CHANNEL = "Fynd"
CSV_PATH = Path(__file__).parent.parent / "data" / "fynd_export.csv"


def load_daily() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    df["date"] = pd.to_datetime(df["Day"], format="%Y-%m-%d")

    # Fynd exports include "previous_period" columns — use current period only
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
