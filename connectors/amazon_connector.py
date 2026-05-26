import io
import pandas as pd

CHANNEL = "Amazon"


def _read_csv(source):
    """Read Amazon CSV, auto-detecting the header row that starts with 'date/time'.
    Works with both file paths and file-like objects (e.g. BytesIO from st.file_uploader)."""
    if hasattr(source, "read"):
        raw = source.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    else:
        with open(source, encoding="utf-8", errors="replace") as f:
            text = f.read()

    lines = text.splitlines()

    # Find the actual header row — works regardless of how many metadata rows Amazon adds
    header_idx = next(
        (i for i, line in enumerate(lines) if line.lower().startswith("date/time")),
        None,
    )
    if header_idx is None:
        raise ValueError("Could not find 'date/time' header row in Amazon CSV.")

    return pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), thousands=",")


def load_daily(source) -> pd.DataFrame:
    df = _read_csv(source)

    # Extract just the date "30 Apr 2026" from "30 Apr 2026 6:35:16 pm UTC"
    df["date"] = pd.to_datetime(
        df["date/time"].astype(str).str.extract(r"(\d{1,2} \w{3} \d{4})")[0],
        format="%d %b %Y",
        errors="coerce",
    )

    # Ensure money columns are numeric (values like "1,657.14" arrive as strings)
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
    result["channel"] = CHANNEL
    return result[["channel", "date", "sku", "orders", "gross_sales",
                   "discounts", "returns", "net_sales", "units_sold"]]
