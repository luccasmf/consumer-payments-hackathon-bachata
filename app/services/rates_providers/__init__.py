"""FX rate providers and aggregation helpers.

Two distinct kinds of source feed the rates conversation:

1. **Rate-table HTTP providers** (subclass :class:`FxProvider`) — one
   GET returns rates for many currencies at once (e.g. ``open.er-api``).
   Listed in :data:`PROVIDERS`; orchestrated by :func:`fetch_all_quotes`.

2. **Per-corridor multi-provider scrapes** — one call returns several
   distinct remittance services for one corridor (e.g. Monito, which
   surfaces Remitly, Wise, Western Union, …). Each row becomes its
   own :class:`FxProviderResult`. Use :func:`fetch_monito_quotes` for
   that source. Stitching the two together happens at the service
   layer in :mod:`app.services.rates_service`.

Adding a new rate-table provider:

1. Create ``app/services/rates_providers/<your_provider>.py`` and
   subclass :class:`FxProvider`.
2. Import it here.
3. Append an instance to :data:`PROVIDERS`.

``fetch_all_quotes`` runs every registered provider concurrently and
discards individual failures so a flaky upstream doesn't block the rest.
"""

import asyncio
import logging

import httpx

from .base import FxProvider, FxProviderResult
from .felix_pago_public import FelixPagoPublicProvider
from .monito import fetch_monito_quotes
from .open_er_api import OpenErApiProvider

logger = logging.getLogger(__name__)

# Project-wide reference / canonical provider. Anything historical (the
# 7-day chart, "as of" label, baseline comparisons) anchors on this one.
BASE_PROVIDER: FxProvider = OpenErApiProvider()

# Order matters: results render in this order. The base provider must
# come first so anything anchoring on ``results[0]`` matches anything
# anchoring on ``BASE_PROVIDER``. Per-corridor multi-provider sources
# (Monito) are stitched in at the service layer; they are not part of
# this list because they need ``(country, amount, currency)`` upfront.
PROVIDERS: list[FxProvider] = [
    BASE_PROVIDER,
    FelixPagoPublicProvider(),
]


async def fetch_all_quotes(
    providers: list[FxProvider] | None = None,
) -> list[FxProviderResult]:
    """
    Query every rate-table provider concurrently. Failures are logged,
    not raised.

    Returns successful results in the same order as the input
    ``providers`` list (or :data:`PROVIDERS` when omitted), with failed
    providers silently dropped.
    """
    chosen = providers if providers is not None else PROVIDERS

    async def safe_fetch(provider: FxProvider) -> FxProviderResult | None:
        try:
            return await provider.fetch_result()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("FX provider %s failed: %s", provider.name, exc)
            return None

    results = await asyncio.gather(*(safe_fetch(p) for p in chosen))
    return [r for r in results if r is not None]


__all__ = [
    "BASE_PROVIDER",
    "FelixPagoPublicProvider",
    "FxProvider",
    "FxProviderResult",
    "OpenErApiProvider",
    "PROVIDERS",
    "fetch_all_quotes",
    "fetch_monito_quotes",
]
