"""Anomaly detection.

Method: modified z-score against a trailing baseline.

    z = 0.6745 * (value - median) / MAD

Why median and MAD (median absolute deviation) rather than mean and standard
deviation: yesterday's spike inflates the mean and the standard deviation at the
same time, so a mean-based z-score partly hides the very event you are hunting.
The median barely moves. 0.6745 rescales MAD so the threshold is comparable to
a normal-distribution sigma; 3.5 is the Iglewicz-Hoaglin convention.

Seasonality is handled by only comparing weekdays with weekdays and weekends
with weekends. Without that, every Saturday looks like a crash.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config

MAD_SCALE = 0.6745


@dataclass
class Anomaly:
    metric: str
    date: pd.Timestamp
    value: float
    baseline: float
    z_score: float
    direction: str          # "up" or "down"
    pct_change: float       # vs baseline median
    is_bad: bool            # does this direction hurt the business?
    baseline_n: int

    @property
    def severity(self) -> str:
        a = abs(self.z_score)
        if a >= 6:
            return "critical"
        return "high" if a >= 4.5 else "moderate"


def _baseline_slice(df: pd.DataFrame, cfg: Config, idx: int) -> pd.DataFrame:
    """Prior days only — never let the current day inform its own baseline."""
    window = df.iloc[max(0, idx - cfg.baseline_days) : idx]
    if cfg.seasonal_split and len(window):
        target_weekend = df.iloc[idx][cfg.date_column].dayofweek >= 5
        same = window[
            (window[cfg.date_column].dt.dayofweek >= 5) == target_weekend
        ]
        # Only use the seasonal subset if it is thick enough to be stable.
        if len(same) >= cfg.min_baseline_points:
            return same
    return window


def detect(df: pd.DataFrame, cfg: Config, target_date=None) -> list[Anomaly]:
    """Check one day (the latest by default) across every configured metric."""
    idx = len(df) - 1 if target_date is None else int(
        df.index[df[cfg.date_column] == pd.Timestamp(target_date)][0]
    )

    row = df.iloc[idx]
    baseline = _baseline_slice(df, cfg, idx)
    found: list[Anomaly] = []

    for metric, bad_direction in cfg.metrics.items():
        value = row[metric]
        history = baseline[metric].dropna()
        if pd.isna(value) or len(history) < cfg.min_baseline_points:
            continue

        median = float(history.median())
        mad = float(np.median(np.abs(history - median)))

        if mad == 0:
            # Perfectly flat history: fall back to std so we do not divide by zero.
            std = float(history.std(ddof=1))
            if std == 0:
                continue
            z = (value - median) / std
        else:
            z = MAD_SCALE * (value - median) / mad

        if abs(z) < cfg.z_threshold:
            continue

        direction = "up" if z > 0 else "down"
        found.append(
            Anomaly(
                metric=metric,
                date=row[cfg.date_column],
                value=float(value),
                baseline=median,
                z_score=round(float(z), 2),
                direction=direction,
                pct_change=round((value - median) / median * 100, 1) if median else float("nan"),
                is_bad=bad_direction in (direction, "both"),
                baseline_n=len(history),
            )
        )

    # Worst first, so the email leads with what matters.
    found.sort(key=lambda a: (not a.is_bad, -abs(a.z_score)))
    return found


def backtest(df: pd.DataFrame, cfg: Config, days: int = 30) -> pd.DataFrame:
    """Replay the last N days to see how often the agent would have fired.

    This is the single most useful thing to show in an interview: it turns
    'I picked a threshold' into 'I checked what that threshold does'.
    """
    rows = []
    for idx in range(max(cfg.min_baseline_points, len(df) - days), len(df)):
        for a in detect(df, cfg, target_date=df.iloc[idx][cfg.date_column]):
            rows.append(
                {
                    "date": a.date.date(),
                    "metric": a.metric,
                    "z_score": a.z_score,
                    "direction": a.direction,
                    "pct_change": a.pct_change,
                    "severity": a.severity,
                    "is_bad": a.is_bad,
                }
            )
    return pd.DataFrame(rows)
