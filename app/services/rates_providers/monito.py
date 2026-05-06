"""Monito.com multi-provider scrape adapter.

Monito (monito.com) is itself a comparison aggregator — for one corridor
it returns several remittance services (Remitly, Wise, Western Union, …).
We expand each row into its own :class:`FxProviderResult` so each
service shows up as a distinct line in the bot's side-by-side reply,
sitting alongside our HTTP rate-table providers (open.er-api).

Every Monito-derived result has ``is_base=False`` — only open.er-api is
flagged as the project's reference provider.
"""

from __future__ import annotations

import logging

from app.services.monito_playwright_service import MonitoPlaywrightService

from .base import FxProviderResult

logger = logging.getLogger(__name__)


async def fetch_monito_quotes(
    country_iso2: str | None,
    amount_usd: float,
    currency_code: str,
    *,
    service: MonitoPlaywrightService | None = None,
) -> list[FxProviderResult]:
    """Run Monito for the corridor and expand each row into its own result.

    Returns ``[]`` on any failure (no corridor mapping, scrape error,
    Playwright not installed, missing currency). Monito is *enrichment*
    layered on top of the API providers and must never break the
    critical path of the rates conversation.
    """
    if not country_iso2 or amount_usd <= 0:
        return []

    monito = service or MonitoPlaywrightService()
    try:
        result = await monito.fetch_raw(
            country_iso2,
            amount_usd,
            receive_currency=currency_code.lower(),
        )
    except Exception as exc:  # broad: scraping is best-effort, never blocks
        logger.warning(
            "Monito fetch failed for %s/%s: %s",
            country_iso2,
            currency_code,
            exc,
        )
        return []

    output: list[FxProviderResult] = []
    for row in result.providers:
        if not row.receive_max or not row.label:
            continue
        rate_per_usd = row.receive_max / amount_usd
        output.append(
            FxProviderResult(
                provider=row.label,
                base="USD",
                rates={currency_code: rate_per_usd},
                source_url=result.url,
                is_base=False,
            )
        )
    return output
