"""Email alerting, plus the two things that decide whether anyone keeps the
alert switched on:

  - a severity gate, so routine wobble does not generate mail
  - a cooldown, so the same metric does not mail every day for a week

Alert fatigue is the reason monitoring tools get muted. Handling it is the part
that shows you have thought past the demo.
"""

import csv
import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from .config import Config
from .detector import Anomaly
from .explain import _fmt, _label

COOLDOWN_DAYS = 3


def should_alert(anomalies: list[Anomaly], cfg: Config) -> tuple[bool, str]:
    harmful = [a for a in anomalies if a.is_bad]
    if not harmful:
        return False, "no harmful anomalies"

    recent = _recently_alerted(cfg)
    fresh = [a for a in harmful if a.metric not in recent]
    if not fresh:
        return False, f"all {len(harmful)} already alerted within {COOLDOWN_DAYS}d"
    return True, f"{len(fresh)} new harmful anomaly(ies)"


def _recently_alerted(cfg: Config) -> set[str]:
    path = Path(cfg.log_path)
    if not path.exists():
        return set()
    cutoff = datetime.now() - timedelta(days=COOLDOWN_DAYS)
    seen = set()
    with path.open() as f:
        for row in csv.DictReader(f):
            try:
                if datetime.fromisoformat(row["alerted_at"]) >= cutoff:
                    seen.add(row["metric"])
            except (ValueError, KeyError):
                continue
    return seen


def build_email(anomalies: list[Anomaly], summary: str, cfg: Config) -> EmailMessage:
    lead = anomalies[0]
    msg = EmailMessage()
    msg["Subject"] = (
        f"[{lead.severity.upper()}] {_label(lead.metric)} {lead.pct_change:+.0f}% "
        f"— {lead.date:%d %b}"
    )
    msg["From"] = cfg.email_from
    msg["To"] = cfg.email_to

    lines = [
        f"Daily metric check — {lead.date:%A %d %B %Y}",
        "=" * 62,
        "",
        "WHAT HAPPENED",
        summary,
        "",
        "THE NUMBERS",
    ]
    for a in anomalies:
        flag = "!" if a.is_bad else " "
        lines.append(
            f" {flag} {_label(a.metric):<20} {_fmt(a.metric, a.value):>12}   "
            f"(typical {_fmt(a.metric, a.baseline)}, {a.pct_change:+.0f}%, {a.severity})"
        )

    lines += [
        "",
        "SUGGESTED CHECKS",
    ]
    lines += [f" - {c}" for c in _checks(anomalies)]
    lines += [
        "",
        "-" * 62,
        f"Baseline: median of the trailing {cfg.baseline_days} comparable days.",
        "Flagged above a modified z-score of "
        f"{cfg.z_threshold}. Automated message — reply to mute a metric.",
    ]
    msg.set_content("\n".join(lines))
    return msg


_CHECKS = {
    "traffic": "Traffic source breakdown — is one channel or geography responsible?",
    "conversion_rate": "Checkout funnel for errors, and any recent site deploy.",
    "refunds": "Refund reasons grouped by SKU and shipping lane.",
    "ad_spend": "Campaign-level spend and CPC changes since the last auction shift.",
    "revenue": "Whether the change is volume or order value.",
    "orders": "Whether analytics tracking is still firing correctly.",
    "avg_order_value": "Active discount codes and product mix.",
}


def _checks(anomalies: list[Anomaly]) -> list[str]:
    out = [_CHECKS[a.metric] for a in anomalies if a.metric in _CHECKS]
    return out or ["Confirm the source data exported correctly."]


def send(msg: EmailMessage, cfg: Config) -> str:
    """Send, or in dry-run write the exact message to disk for the portfolio."""
    if cfg.dry_run:
        os.makedirs(cfg.output_dir, exist_ok=True)
        path = Path(cfg.output_dir) / "sample_alert_email.txt"
        path.write_text(
            f"To: {msg['To']}\nFrom: {msg['From']}\nSubject: {msg['Subject']}\n\n"
            + msg.get_content()
        )
        return f"dry-run: written to {path}"

    if not (cfg.smtp_user and cfg.smtp_password):
        return "not sent: SMTP_USER / SMTP_PASSWORD are not set"

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
        server.starttls()
        server.login(cfg.smtp_user, cfg.smtp_password)
        server.send_message(msg)
    return f"sent to {cfg.email_to}"


def log(anomalies: list[Anomaly], cfg: Config, outcome: str) -> None:
    os.makedirs(cfg.output_dir, exist_ok=True)
    path = Path(cfg.log_path)
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(
                ["alerted_at", "metric_date", "metric", "value", "baseline",
                 "pct_change", "z_score", "severity", "harmful", "outcome"]
            )
        for a in anomalies:
            writer.writerow(
                [datetime.now().isoformat(timespec="seconds"), f"{a.date:%Y-%m-%d}",
                 a.metric, round(a.value, 2), round(a.baseline, 2), a.pct_change,
                 a.z_score, a.severity, a.is_bad, outcome]
            )
