# retail-metric-watch

Automated anomaly detection and alerting for daily retail metrics.

Reads the daily sales spreadsheet each morning, decides whether anything
unusual happened, explains it in plain English, and emails whoever needs to
know — replacing the habit of a manager opening the file at 8am to check
whether yesterday was fine.

---

## What it does

```
Excel file  →  clean & validate  →  detect  →  explain  →  decide  →  email + log
```

Run it:

```bash
pip install -r requirements.txt
python make_sample_data.py     # creates 120 days of sample data
python run_agent.py            # checks the most recent day
```

Other modes:

```bash
python run_agent.py --backtest 60      # how often would this have fired?
python run_agent.py --date 2026-08-19  # check a specific day
python run_agent.py --send             # actually send via SMTP
```

---

## How detection works

Each metric is compared against **the median of the trailing 28 comparable
days**, using a modified z-score:

```
z = 0.6745 × (value − median) / MAD          MAD = median absolute deviation
```

Flagged when `|z| ≥ 3.5`.

**Why median and MAD instead of mean and standard deviation.** A spike inflates
the mean *and* the standard deviation at the same time, so a mean-based z-score
partially hides the very event you are looking for. The median barely moves.
The 0.6745 constant rescales MAD to be comparable to a normal-distribution
sigma, which is where the conventional 3.5 threshold comes from.

**Why "comparable" days.** Weekends run about 18% quieter than weekdays here, so
a Saturday judged against a weekday-heavy baseline is being compared to the
wrong normal. The agent compares weekdays to weekdays and weekends to weekends,
falling back to the full window when the seasonal subset is too thin.

**Measured effect: none, on this data.** Backtested at the operating threshold,
seasonal and non-seasonal produce identical flags. At looser thresholds the
*non-seasonal* version flags fewer days, not more:

| z-threshold | seasonal | non-seasonal |
|---|---|---|
| 3.5 | 6 flags | 6 flags |
| 3.0 | 9 | 9 |
| 2.5 | 20 | 18 |
| 2.0 | 50 | 34 |

The intuition that a mixed baseline causes weekend false alarms is wrong, and
the table shows why: mixing weekdays and weekends *widens* the MAD, which
widens the normal band and makes the detector less sensitive overall. It
suppresses flags rather than manufacturing them.

The split stays in because comparing like with like is still the correct
baseline, and seasonality strong enough to matter is common in real retail data
even though this sample's is too mild to move the threshold. But it is
insurance, not a demonstrated win — and the honest version of that claim is
this table, not a confident assertion.

**Direction matters.** Every metric is configured with which direction is bad
news. Refunds rising is a problem; revenue rising is not. Only harmful
anomalies trigger email — benign ones are logged and reported but do not wake
anyone up.

---

## Measured performance

Backtested over the last 60 days of the sample data, which contains three
deliberately planted incidents:

| | Result |
|---|---|
| Planted incidents detected | 3 of 3 |
| Days generating an alert | 4 of 60 (7%) |
| Benign flags | 1 (conversion rate +15%, correctly classified as not harmful) |
| False alarms that would have emailed | 0 |

Being able to state this is the difference between "I chose a threshold" and
"I checked what that threshold does". Run `--backtest` after any config change.

---

## The intelligence layer

Detection finds *what* moved. This layer works out *what it means*.

**Cross-metric patterns.** Some combinations mean something specific that no
single-metric detector can see. Traffic up + conversion down is not two
problems, it is one: traffic quality. The agent recognises five such patterns
and states the reading.

**Narrative generation.** If `ANTHROPIC_API_KEY` is set, Claude writes the
summary from a strictly bounded JSON payload of the detected facts, with a
prompt that forbids inventing numbers or causes. Without a key, a rule-based
writer produces a plainer but equally correct summary.

The fallback is deliberate. An alerting tool that goes quiet because an API
call failed is worse than no tool at all, because people have stopped checking
manually by then.

---

## Alert fatigue handling

The reason monitoring tools get muted:

- **Severity gate** — only harmful anomalies generate email.
- **Cooldown** — a metric that already alerted within 3 days is suppressed and
  logged rather than re-sent, so one ongoing problem does not mail daily for a
  week.
- **Suggested checks** — every alert names the specific thing to go look at, so
  the recipient has a next action rather than a number.

---

## Configuration

Everything tunable is in `agent/config.py`: which metrics to watch, which
direction is harmful for each, baseline window, threshold, and email settings.

Email is **dry-run by default** — it writes the exact message to
`output/sample_alert_email.txt` instead of sending. This is what you screenshot
for a portfolio. To send for real, set the environment variables and pass
`--send`:

```bash
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="your-app-password"   # Gmail app password, not your login
export ALERT_TO="manager@company.com"
export ANTHROPIC_API_KEY="sk-ant-..."      # optional
```

Gmail requires an [app password](https://support.google.com/accounts/answer/185833)
with 2FA enabled; your normal password will be rejected.

---

## Running it daily

Cron, on Linux or macOS — 8am every weekday:

```
0 8 * * 1-5 cd /path/to/anomaly-agent && /usr/bin/python3 run_agent.py --send >> output/cron.log 2>&1
```

Windows: Task Scheduler, same command. GitHub Actions works too if the data
lives somewhere fetchable, and gives you a public run history for the portfolio.

---

## File map

| File | Purpose |
|---|---|
| `run_agent.py` | Entry point and CLI |
| `agent/config.py` | Every tunable setting |
| `agent/loader.py` | Read, validate, clean; reports data quality |
| `agent/detector.py` | Modified z-score detection + backtest |
| `agent/explain.py` | Cross-metric patterns, LLM and rule-based summaries |
| `agent/alert.py` | Email construction, cooldown, sending, logging |
| `make_sample_data.py` | Generates sample data with planted anomalies |
| `output/alert_log.csv` | History of every flag and what was done about it |

---

## Using your own data

Point `excel_path` at your file and edit the `metrics` dict in
`agent/config.py` to your column names and harmful directions. The loader
normalises column names to lowercase with underscores, so `Conversion Rate`
becomes `conversion_rate`.

You need roughly 6 weeks of history before the baseline is meaningful.

---

## Known limitations

Worth stating in an interview before anyone asks:

- **Point anomalies only.** A metric that decays 3% a day for a month never
  trips the threshold, because the baseline decays with it. Trend detection is
  a separate problem.
- **No holiday awareness.** Black Friday will flag as a critical anomaly. A
  calendar of known events is the obvious next feature.
- **Patterns are hand-written rules**, not learned. That is a deliberate
  trade-off: five rules that a manager can read and challenge beat a model
  nobody can interrogate at this scale.
- **Correlation, not causation.** The agent says what to check, never what
  caused it.
