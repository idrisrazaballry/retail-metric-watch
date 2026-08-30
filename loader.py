"""Reads the Excel file and makes it trustworthy before anything else touches it.

Most of the bugs in a project like this are here, not in the maths: a renamed
column, a date stored as text, a duplicated row from a re-export.
"""

import pandas as pd

from .config import Config


class DataQualityError(Exception):
    """Raised when the file is too broken to analyse honestly."""


def load(cfg: Config) -> pd.DataFrame:
    df = pd.read_excel(cfg.excel_path, sheet_name=cfg.sheet_name)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    if cfg.date_column not in df.columns:
        raise DataQualityError(
            f"No '{cfg.date_column}' column. Found: {list(df.columns)}"
        )

    missing = [m for m in cfg.metrics if m not in df.columns]
    if missing:
        raise DataQualityError(f"Configured metrics not in sheet: {missing}")

    df[cfg.date_column] = pd.to_datetime(df[cfg.date_column], errors="coerce")
    bad_dates = int(df[cfg.date_column].isna().sum())
    if bad_dates:
        df = df.dropna(subset=[cfg.date_column])

    # Numeric coercion: a stray "1,240" or "N/A" becomes NaN rather than
    # silently poisoning the median.
    for metric in cfg.metrics:
        df[metric] = pd.to_numeric(df[metric], errors="coerce")

    before = len(df)
    df = df.drop_duplicates(subset=[cfg.date_column], keep="last")
    duplicates = before - len(df)

    df = df.sort_values(cfg.date_column).reset_index(drop=True)

    if len(df) < cfg.min_baseline_points + 1:
        raise DataQualityError(
            f"Only {len(df)} usable rows; need at least {cfg.min_baseline_points + 1}."
        )

    df.attrs["quality"] = {
        "rows": len(df),
        "dropped_bad_dates": bad_dates,
        "dropped_duplicates": duplicates,
        "null_counts": {m: int(df[m].isna().sum()) for m in cfg.metrics},
        "date_range": (
            f"{df[cfg.date_column].min():%Y-%m-%d} to {df[cfg.date_column].max():%Y-%m-%d}"
        ),
        "gap_days": _find_gaps(df[cfg.date_column]),
    }
    return df


def _find_gaps(dates: pd.Series) -> list[str]:
    """Missing days matter — a silent gap looks like a quiet week."""
    expected = pd.date_range(dates.min(), dates.max(), freq="D")
    missing = expected.difference(pd.DatetimeIndex(dates))
    return [f"{d:%Y-%m-%d}" for d in missing[:10]]
