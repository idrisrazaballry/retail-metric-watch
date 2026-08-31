"""Entry point. One run = one day checked.

    python run_agent.py                 # check the latest day, dry-run email
    python run_agent.py --send          # actually send via SMTP
    python run_agent.py --date 2026-08-19
    python run_agent.py --backtest 45   # how often would this have fired?
"""

import argparse
import sys

from agent import alert, explain
from agent.config import Config
from agent.detector import backtest, detect
from agent.loader import DataQualityError, load


def main() -> int:
    p = argparse.ArgumentParser(description="Daily business-metric anomaly agent")
    p.add_argument("--file", help="path to the Excel file")
    p.add_argument("--date", help="check a specific date (YYYY-MM-DD)")
    p.add_argument("--send", action="store_true", help="really send the email")
    p.add_argument("--backtest", type=int, metavar="N", help="replay the last N days")
    p.add_argument("--threshold", type=float, help="override the z-score threshold")
    args = p.parse_args()

    cfg = Config()
    if args.file:
        cfg.excel_path = args.file
    if args.send:
        cfg.dry_run = False
    if args.threshold:
        cfg.z_threshold = args.threshold

    try:
        df = load(cfg)
    except (FileNotFoundError, DataQualityError) as exc:
        print(f"Could not read the data: {exc}", file=sys.stderr)
        return 1

    quality = df.attrs["quality"]
    print(f"Loaded {quality['rows']} rows ({quality['date_range']})")
    if quality["dropped_duplicates"] or quality["gap_days"]:
        print(
            f"  data notes: {quality['dropped_duplicates']} duplicate date(s) dropped, "
            f"{len(quality['gap_days'])} missing day(s)"
        )

    if args.backtest:
        results = backtest(df, cfg, args.backtest)
        print(f"\nBacktest over the last {args.backtest} days")
        if results.empty:
            print("  no anomalies — the threshold may be too loose")
        else:
            print(results.to_string(index=False))
            days = results["date"].nunique()
            print(
                f"\n  {len(results)} flags across {days} day(s) "
                f"= {days / args.backtest:.0%} of days would have generated an alert."
            )
        return 0

    anomalies = detect(df, cfg, target_date=args.date)
    day = args.date or f"{df[cfg.date_column].max():%Y-%m-%d}"
    print(f"\nChecked {day}: {len(anomalies)} anomaly(ies) above z={cfg.z_threshold}")

    if not anomalies:
        print("  Everything within normal range. No alert.")
        return 0

    for a in anomalies:
        mark = "HARMFUL" if a.is_bad else "benign "
        print(
            f"  [{mark}] {a.metric:<16} {a.pct_change:+7.1f}%  "
            f"z={a.z_score:+6.2f}  {a.severity}"
        )

    summary = explain.summarize(anomalies, quality, cfg)
    print("\nSummary\n-------")
    print(explain.wrap(summary))

    ok, reason = alert.should_alert(anomalies, cfg)
    print(f"\nAlert decision: {'SEND' if ok else 'HOLD'} ({reason})")
    if ok:
        msg = alert.build_email(anomalies, summary, cfg)
        print(f"  {alert.send(msg, cfg)}")
        alert.log(anomalies, cfg, "alerted")
    else:
        alert.log(anomalies, cfg, f"suppressed: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
