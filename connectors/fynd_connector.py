import pandas as pd

CHANNEL = "Fynd"


def load_daily(source) -> pd.DataFrame:
    """source: a file path, file-like object, or BytesIO from st.file_uploader."""
    df = pd.read_csv(source)
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
    result["channel"] = CHANNEL
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]
