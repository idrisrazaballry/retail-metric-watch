"""
Generates a realistic sample Excel file of daily e-commerce metrics.

Three anomalies are deliberately planted so you can verify the detector works:
  - Day -3 : traffic spike with a conversion-rate collapse (bot traffic pattern)
  - Day -2 : refunds spike (quality/fulfilment problem)
  - Day -1 : cost per acquisition jump (ad auction problem)

Run:  python make_sample_data.py
"""

import numpy as np
import pandas as pd
from openpyxl.styles import Font

RNG = np.random.default_rng(42)
DAYS = 120


def build() -> pd.DataFrame:
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=DAYS, freq="D")
    t = np.arange(DAYS)

    # Weekly seasonality: weekends are quieter for B2C retail.
    dow = dates.dayofweek.to_numpy()
    weekend = np.where(dow >= 5, 0.82, 1.0)

    # Slow organic growth plus noise.
    trend = 1 + 0.0018 * t

    traffic = 14_000 * trend * weekend * RNG.normal(1, 0.05, DAYS)
    conversion = 0.0265 * RNG.normal(1, 0.06, DAYS)
    aov = 62.0 * RNG.normal(1, 0.04, DAYS)
    refund_rate = 0.031 * RNG.normal(1, 0.12, DAYS)
    cpc = 0.94 * RNG.normal(1, 0.07, DAYS)

    # --- planted anomalies -------------------------------------------------
    traffic[-3] *= 2.35          # sudden flood of low-quality traffic
    conversion[-3] *= 0.42       # ...which does not convert
    refund_rate[-2] *= 3.10      # bad batch shipped
    cpc[-1] *= 1.95              # ad costs blow up
    # -----------------------------------------------------------------------

    orders = np.round(traffic * conversion)
    revenue = orders * aov
    refunds = np.round(orders * refund_rate)
    ad_spend = traffic * 0.55 * cpc  # ~55% of traffic is paid

    df = pd.DataFrame(
        {
            "date": dates,
            "traffic": np.round(traffic).astype(int),
            "orders": orders.astype(int),
            "revenue": np.round(revenue, 2),
            "conversion_rate": np.round(orders / traffic, 5),
            "refunds": refunds.astype(int),
            "ad_spend": np.round(ad_spend, 2),
        }
    )
    df["avg_order_value"] = np.round(df["revenue"] / df["orders"], 2)
    return df


if __name__ == "__main__":
    df = build()
    path = "data/daily_business_metrics.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        df.to_excel(xl, sheet_name="daily_metrics", index=False)
        sheet = xl.sheets["daily_metrics"]
        for col, width in zip("ABCDEFGH", [12, 10, 9, 12, 16, 10, 11, 16]):
            sheet.column_dimensions[col].width = width
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in sheet.iter_rows(min_row=2, min_col=1, max_col=1):
            row[0].number_format = "yyyy-mm-dd"

    print(f"Wrote {path}  ({len(df)} rows, {df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d})")
    print(df.tail(4).to_string(index=False))
