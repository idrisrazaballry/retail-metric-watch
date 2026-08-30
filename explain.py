"""The intelligence layer: turns numbers into something a manager will read.

Two paths, and the fallback is not an afterthought:

  1. If ANTHROPIC_API_KEY is set, Claude writes the narrative from a strictly
     bounded set of facts. The prompt forbids inventing causes.
  2. Otherwise, a rule-based writer produces a plainer but still correct summary.

The agent must never go silent because an API call failed. An alerting tool
that stops alerting is worse than no alerting tool, because people trust it.
"""

import json
import textwrap

from .config import Config
from .detector import Anomaly

# Co-occurring anomalies that mean something specific together. This encodes
# the analyst judgement that a per-metric detector cannot see on its own.
PATTERNS = [
    (
        {("traffic", "up"), ("conversion_rate", "down")},
        "Traffic quality",
        "Volume rose while conversion fell. The extra visitors are converting far "
        "worse than usual, which points at bot traffic, a broad-match campaign "
        "change, or a landing page mismatch rather than genuine demand.",
    ),
    (
        {("orders", "down"), ("traffic", "down")},
        "Demand or tracking",
        "Traffic and orders fell together, in proportion. That is either a real "
        "demand drop or a tracking outage — check whether the analytics tag is "
        "still firing before treating it as a business problem.",
    ),
    (
        {("refunds", "up")},
        "Fulfilment or quality",
        "Refunds jumped without a matching rise in orders, which usually traces "
        "to a specific batch, SKU, or shipping lane rather than to overall volume.",
    ),
    (
        {("ad_spend", "up"), ("orders", "down")},
        "Acquisition efficiency",
        "Spend rose while orders did not follow. Cost per acquisition is "
        "deteriorating and the budget is buying less than it did last week.",
    ),
    (
        {("revenue", "down"), ("avg_order_value", "down")},
        "Pricing or mix",
        "Revenue fell on lower order value rather than lower volume, which "
        "suggests discounting or a shift in product mix.",
    ),
]


def find_patterns(anomalies: list[Anomaly]) -> list[tuple[str, str]]:
    signature = {(a.metric, a.direction) for a in anomalies}
    return [
        (name, text) for required, name, text in PATTERNS if required <= signature
    ]


def _facts(anomalies: list[Anomaly], quality: dict) -> dict:
    return {
        "date": f"{anomalies[0].date:%Y-%m-%d}",
        "data_range": quality.get("date_range"),
        "anomalies": [
            {
                "metric": a.metric,
                "value": round(a.value, 2),
                "typical": round(a.baseline, 2),
                "change_pct": a.pct_change,
                "direction": a.direction,
                "z_score": a.z_score,
                "severity": a.severity,
                "harmful": a.is_bad,
            }
            for a in anomalies
        ],
        "patterns": [{"name": n, "reading": t} for n, t in find_patterns(anomalies)],
    }


PROMPT = """You are writing an alert for a busy operations manager who has not \
looked at the data. Below are anomalies detected in daily e-commerce metrics, \
as JSON.

{facts}

Write 3-5 sentences of plain business English.

Rules you must follow:
- Lead with the single most consequential change and what it costs or risks.
- Use the supplied numbers. Do not invent any number that is not in the JSON.
- You may repeat the reading in "patterns" but must not invent a new cause. If \
the cause is unknown, say what should be checked instead.
- No bullet points, no headings, no greeting, no sign-off.
- Never say "anomaly detected" or "z-score". Say what happened.
"""


def _llm_summary(facts: dict, cfg: Config) -> str | None:
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=cfg.api_key)
        msg = client.messages.create(
            model=cfg.model,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(facts=json.dumps(facts, indent=2)),
                }
            ],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as exc:  # noqa: BLE001 - never let the alert die here
        print(f"  ! LLM summary unavailable ({type(exc).__name__}), using fallback.")
        return None


def _rule_summary(anomalies: list[Anomaly]) -> str:
    lead = anomalies[0]
    verb = "rose" if lead.direction == "up" else "fell"
    parts = [
        f"{_label(lead.metric)} {verb} to {_fmt(lead.metric, lead.value)} on "
        f"{lead.date:%A %d %B}, against a typical {_fmt(lead.metric, lead.baseline)} "
        f"({lead.pct_change:+.0f}%)."
    ]

    others = anomalies[1:]
    if others:
        clauses = [
            f"{_label(o.metric).lower()} {o.pct_change:+.0f}%" for o in others
        ]
        parts.append(f"Moving with it: {', '.join(clauses)}.")

    for _, reading in find_patterns(anomalies):
        parts.append(reading)

    harmful = [a for a in anomalies if a.is_bad]
    parts.append(
        f"{len(harmful)} of {len(anomalies)} changes work against the business; "
        "worth a look before the next daily review."
        if harmful
        else "None of these changes are harmful in themselves, but they are outside "
        "the normal range and worth confirming."
    )
    return " ".join(parts)


def summarize(anomalies: list[Anomaly], quality: dict, cfg: Config) -> str:
    if not anomalies:
        return "All monitored metrics are within their normal range."
    facts = _facts(anomalies, quality)
    if cfg.use_llm and cfg.api_key:
        text = _llm_summary(facts, cfg)
        if text:
            return text
    return _rule_summary(anomalies)


# --- small formatting helpers ------------------------------------------------

_LABELS = {
    "conversion_rate": "Conversion rate",
    "avg_order_value": "Average order value",
    "ad_spend": "Ad spend",
}

_MONEY = {"revenue", "ad_spend", "avg_order_value"}


def _label(metric: str) -> str:
    return _LABELS.get(metric, metric.replace("_", " ").capitalize())


def _fmt(metric: str, value: float) -> str:
    if metric == "conversion_rate":
        return f"{value * 100:.2f}%"
    if metric in _MONEY:
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def wrap(text: str, width: int = 78) -> str:
    return "\n".join(textwrap.wrap(text, width))
