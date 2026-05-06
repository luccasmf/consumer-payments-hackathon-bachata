"""Felix Pago public FX — same JSON as felixpago.com currency converter.

The English converter page embeds a script that loads::

    https://us-central1-felix-tech-production.cloudfunctions.net/all_rates_public

That endpoint returns per-currency rows with ``base`` and/or ``tradfi_fv``
string fields. The site's ``publicRateBase`` helper prefers ``base`` when it
parses to a positive float; we mirror that and fall back to ``tradfi_fv``.
"""

from __future__ import annotations

from typing import Any

import httpx

from .base import FxProvider


def _felix_row_to_rate(row: Any) -> float | None:
    if not isinstance(row, dict):
        return None
    base_raw = row.get("base")
    if base_raw not in (None, ""):
        try:
            v = float(base_raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    tv = row.get("tradfi_fv")
    if tv not in (None, ""):
        try:
            v = float(tv)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return None


class FelixPagoPublicProvider(FxProvider):
    """USD-base rates from Felix's public Cloud Function (marketing site source)."""

    name = "felixpago.com"
    source_url = "https://www.felixpago.com/en/currency-converter"
    base = "USD"
    is_base = False

    URL = (
        "https://us-central1-felix-tech-production.cloudfunctions.net/all_rates_public"
    )

    async def fetch(self, client: httpx.AsyncClient) -> dict[str, float]:
        response = await client.get(self.URL)
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"Unexpected Felix rates root type: {type(data)!r}")

        rates: dict[str, float] = {}
        for code, row in data.items():
            if not isinstance(code, str) or len(code) != 3:
                continue
            rate = _felix_row_to_rate(row)
            if rate is not None:
                rates[code] = rate

        if not rates:
            raise ValueError(f"Felix rates payload had no usable rows: {data!r}")

        return rates
