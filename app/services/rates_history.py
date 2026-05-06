"""
Historical FX rates + chart URL builder.

Used to attach a 7-day USD→<currency> trend chart to live quote replies.

Why a separate fetcher? Our base provider (``open.er-api`` free tier) only
exposes the *latest* rate, not history. ``fawazahmed0/currency-api`` mirrored
on jsDelivr is free, key-less, covers every currency we care about (including
COP / GTQ / HNL / DOP that ECB-based feeds skip), and supports historical
lookups by date — perfect for a small trend chart.

The chart itself is rendered by https://quickchart.io (also free, key-less,
HTTPS) so Kapso/Meta can fetch and forward the image URL directly.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# ``@<date|latest>`` selects a snapshot tagged on that date. ``latest``
# always works; historical dates work back many years.
_FAWAZ_URL_TEMPLATE = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}"
    "/v1/currencies/usd.json"
)

QUICKCHART_URL = "https://quickchart.io/chart"

DEFAULT_DAYS = 7


async def _fetch_one_day(
    client: httpx.AsyncClient,
    date: dt.date,
    currency_lower: str,
) -> tuple[dt.date, float] | None:
    """Fetch the USD→currency rate for ``date``. Returns ``None`` on failure."""
    url = _FAWAZ_URL_TEMPLATE.format(date=date.isoformat())
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        rate = data.get("usd", {}).get(currency_lower)
        if rate is None:
            return None
        return (date, float(rate))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("History fetch failed for %s on %s: %s", currency_lower, date, exc)
        return None


async def fetch_recent_history(
    currency: str,
    days: int = DEFAULT_DAYS,
    *,
    today: dt.date | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, float]:
    """
    Return ``{iso_date: rate}`` for the last ``days`` calendar days,
    ascending by date. Missing days are silently dropped (the API may not
    have published a snapshot for weekends/holidays for some currencies).
    """
    if days <= 0:
        return {}

    today = today or dt.date.today()
    target_dates = [today - dt.timedelta(days=i) for i in range(days)]
    currency_lower = currency.lower()

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        results = await asyncio.gather(
            *(_fetch_one_day(client, d, currency_lower) for d in target_dates)
        )
    finally:
        if owns_client:
            await client.aclose()

    successful = sorted(r for r in results if r is not None)
    return {date.isoformat(): rate for date, rate in successful}


def build_chart_url(
    currency: str,
    history: dict[str, float],
    *,
    title: str | None = None,
) -> str | None:
    """
    Build a QuickChart.io URL rendering ``history`` as a small line chart.

    Returns ``None`` when there's nothing to plot. The URL stays well
    under WhatsApp's media-URL length budget for the size of payload we
    pass (≤ ~10 data points).
    """
    if not history:
        return None

    chart_title = title or (
        f"USD → {currency.upper()} — last {len(history)} days"
    )

    config: dict = {
        "type": "line",
        "data": {
            "labels": list(history.keys()),
            "datasets": [
                {
                    "label": f"USD → {currency.upper()}",
                    "data": list(history.values()),
                    "borderColor": "rgb(34, 139, 230)",
                    "backgroundColor": "rgba(34, 139, 230, 0.15)",
                    "borderWidth": 3,
                    "fill": True,
                    "tension": 0.35,
                    "pointRadius": 4,
                }
            ],
        },
        "options": {
            "title": {"display": True, "text": chart_title, "fontSize": 16},
            "legend": {"display": False},
            "scales": {
                "yAxes": [{"ticks": {"beginAtZero": False}}],
            },
        },
    }

    encoded = quote(json.dumps(config, separators=(",", ":")))
    return f"{QUICKCHART_URL}?c={encoded}&w=600&h=320&bkg=white"


async def get_history_chart_url(
    currency: str,
    days: int = DEFAULT_DAYS,
    *,
    title: str | None = None,
) -> str | None:
    """
    Convenience: fetch history and build a chart URL in one shot.

    Returns ``None`` if no history could be fetched. Never raises — the
    chart is *enrichment*, not a critical path.
    """
    try:
        history = await fetch_recent_history(currency, days=days)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("History pipeline failed for %s: %s", currency, exc)
        return None
    return build_chart_url(currency, history, title=title)
