"""All tunable settings live here, so nothing is buried in the logic."""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # --- input ---------------------------------------------------------
    excel_path: str = "data/daily_business_metrics.xlsx"
    sheet_name: str = "daily_metrics"
    date_column: str = "date"

    # Metrics to watch, and which direction is bad news for the business.
    # "up" = a spike is bad, "down" = a drop is bad, "both" = either.
    #
    # The direction is a retail judgement call, not a statistical one. Notes
    # explain the reasoning so it can be defended or challenged:
    metrics: dict = field(
        default_factory=lambda: {
            "revenue": "down",            # the headline number
            "orders": "down",             # volume, separate from value
            "traffic": "both",            # a spike is as suspicious as a drop
            "conversion_rate": "down",    # the health check on traffic quality
            "refunds": "up",              # quality/fulfilment early warning
            "ad_spend": "up",             # budget overrun or auction shift
            "avg_order_value": "both",    # down = discounting, up = mix shift
            # Add if your data has them — high-value retail signals:
            # "stockouts": "up",          # lost sales you never see in revenue
            # "cart_abandonment": "up",   # checkout breakage, leads revenue
            # "return_rate": "up",        # normalises refunds against volume
            # "gross_margin": "down",     # revenue can rise while margin falls
            # "units_per_order": "down",  # cross-sell / bundling health
        }
    )

    # --- detection -----------------------------------------------------
    baseline_days: int = 28       # trailing window used as "normal"
    min_baseline_points: int = 10  # refuse to judge on thinner history
    z_threshold: float = 3.5      # Iglewicz-Hoaglin standard for modified z
    seasonal_split: bool = True   # compare weekdays to weekdays only

    # --- intelligence layer --------------------------------------------
    use_llm: bool = True          # falls back to templates if no API key
    model: str = "claude-sonnet-5"
    api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))

    # --- alerting ------------------------------------------------------
    email_to: str = os.environ.get("ALERT_TO", "manager@example.com")
    email_from: str = os.environ.get("ALERT_FROM", "anomaly-agent@example.com")
    smtp_host: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.environ.get("SMTP_PORT", 587))
    smtp_user: str | None = os.environ.get("SMTP_USER")
    smtp_password: str | None = os.environ.get("SMTP_PASSWORD")
    dry_run: bool = True          # write the email to disk instead of sending

    # --- output --------------------------------------------------------
    output_dir: str = "output"
    log_path: str = "output/alert_log.csv"
