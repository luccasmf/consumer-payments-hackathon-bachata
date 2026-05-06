"""Monito compare scrape (Playwright) as a reusable async service.

Install browser once: ``playwright install chromium``

CLI (from repo root):

  python -m app.services.monito_playwright_service --to-country mx --amount 500 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.services.monito_compare import (
    MonitoCompareResult,
    fetch_monito_compare,
    parse_monito_compare_url,
)

# ISO 3166-1 alpha-2 → default receive currency (ISO 4217) for Monito compare paths.
# Override per call with ``receive_currency=`` when missing or wrong for the corridor.
_RECEIVE_CURRENCY_BY_ISO2: dict[str, str] = {
    "ar": "ars",
    "bo": "bob",
    "br": "brl",
    "cl": "clp",
    "co": "cop",
    "cr": "crc",
    "do": "dop",
    "ec": "usd",
    "gt": "gtq",
    "hn": "hnl",
    "mx": "mxn",
    "ni": "nio",
    "pa": "usd",
    "pe": "pen",
    "py": "pyg",
    "sv": "usd",
    "uy": "uyu",
    "us": "usd",
    "ve": "ves",
    "in": "inr",
    "ph": "php",
    "ng": "ngn",
    "ke": "kes",
    "gh": "ghs",
    "za": "zar",
    "pl": "pln",
    "gb": "gbp",
    "eu": "eur",
    "fr": "eur",
    "de": "eur",
    "es": "eur",
    "it": "eur",
    "pt": "eur",
}


def _default_receive_currency(destination_country: str) -> str:
    code = destination_country.strip().lower()
    try:
        return _RECEIVE_CURRENCY_BY_ISO2[code]
    except KeyError as e:
        raise ValueError(
            f"No default receive currency for destination {destination_country!r}. "
            "Pass receive_currency explicitly (3-letter ISO code, e.g. mxn)."
        ) from e


def providers_from_result(result: MonitoCompareResult, *, top: int = 0) -> list[dict[str, Any]]:
    """JSON-serializable provider rows (rank, slug, label, receive_max)."""
    rows = list(result.providers)
    if top > 0:
        rows = rows[:top]
    return [
        {"rank": i, "slug": r.slug, "label": r.label, "receive_max": r.receive_max}
        for i, r in enumerate(rows, start=1)
    ]


class MonitoPlaywrightService:
    """Scrape Monito money-transfer compare for a destination country and send amount."""

    def __init__(
        self,
        *,
        from_country: str = "us",
        send_currency: str = "usd",
        locale: str = "en",
        headless: bool = True,
        timeout_s: float = 120.0,
        poll_s: float = 0.5,
        scroll_pause_s: float = 0.8,
        scroll_max_rounds: int = 12,
    ) -> None:
        self.from_country = from_country
        self.send_currency = send_currency
        self.locale = locale
        self.headless = headless
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.scroll_pause_s = scroll_pause_s
        self.scroll_max_rounds = scroll_max_rounds

    async def fetch_raw(
        self,
        destination_country: str,
        amount: int | float,
        *,
        receive_currency: str | None = None,
        url: str | None = None,
    ) -> MonitoCompareResult:
        """Run Playwright and return the structured :class:`MonitoCompareResult`."""
        dest = destination_country.strip().lower()
        if url:
            parsed = parse_monito_compare_url(url)
            if parsed:
                recv = (receive_currency or parsed[3]).strip().lower()
            else:
                recv = (receive_currency or _default_receive_currency(dest)).strip().lower()
        else:
            recv = (receive_currency or _default_receive_currency(dest)).strip().lower()
        return await fetch_monito_compare(
            url,
            from_country=self.from_country,
            to_country=dest,
            send_currency=self.send_currency,
            receive_currency=recv,
            send_amount=amount,
            locale=self.locale,
            headless=self.headless,
            timeout_s=self.timeout_s,
            poll_s=self.poll_s,
            scroll_pause_s=self.scroll_pause_s,
            scroll_max_rounds=self.scroll_max_rounds,
        )

    async def compare(
        self,
        destination_country: str,
        amount: int | float,
        *,
        receive_currency: str | None = None,
        url: str | None = None,
        top: int = 0,
    ) -> list[dict[str, Any]]:
        """Scrape Monito for ``destination_country`` (ISO2) and ``amount`` in ``send_currency``.

        If ``url`` is set and matches Monito's compare path, corridor amounts and
        currencies are taken from the URL; otherwise ``amount`` and inferred
        ``receive_currency`` apply.

        Returns a JSON-serializable list of provider rows (suitable for ``json.dumps``).
        """
        result = await self.fetch_raw(
            destination_country,
            amount,
            receive_currency=receive_currency,
            url=url,
        )
        return providers_from_result(result, top=top)

    async def compare_json(
        self,
        destination_country: str,
        amount: int | float,
        *,
        receive_currency: str | None = None,
        url: str | None = None,
        top: int = 0,
        indent: int | None = 2,
    ) -> str:
        """Same as :meth:`compare` but returns a JSON string."""
        data = await self.compare(
            destination_country,
            amount,
            receive_currency=receive_currency,
            url=url,
            top=top,
        )
        return json.dumps(data, indent=indent)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Monito compare page (Playwright). "
        "Omit --url to build from country/currency/amount flags."
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Full Monito compare URL (overrides corridor flags below)",
    )
    parser.add_argument("--from-country", default="us", help="Sender country ISO2, e.g. us")
    parser.add_argument("--to-country", default="co", help="Recipient country ISO2, e.g. co, mx")
    parser.add_argument("--send-currency", default="usd", help="Sent currency ISO3, e.g. usd")
    parser.add_argument(
        "--receive-currency",
        default=None,
        help="Received currency ISO3 (default: inferred from --to-country when omitted)",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=100.0,
        help="Send amount in send-currency (path segment on Monito)",
    )
    parser.add_argument("--locale", default="en", help="Monito locale path segment, e.g. en")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll", type=float, default=0.5)
    parser.add_argument("--scroll-pause", type=float, default=0.8)
    parser.add_argument("--scroll-rounds", type=int, default=12)
    parser.add_argument("--top", type=int, default=0, help="Limit rows (0 = all)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON to stdout",
    )
    parser.add_argument(
        "--timings",
        action="store_true",
        help="After text table, print timing fields (JSON mode prints providers list only)",
    )
    args = parser.parse_args()

    recv = args.receive_currency
    if recv is None and not args.url:
        recv = _default_receive_currency(args.to_country)

    service = MonitoPlaywrightService(
        from_country=args.from_country,
        send_currency=args.send_currency,
        locale=args.locale,
        headless=not args.headed,
        timeout_s=args.timeout,
        poll_s=args.poll,
        scroll_pause_s=args.scroll_pause,
        scroll_max_rounds=args.scroll_rounds,
    )

    result = asyncio.run(
        service.fetch_raw(
            args.to_country,
            args.amount,
            receive_currency=recv,
            url=args.url,
        )
    )

    rows = list(result.providers)
    if args.top > 0:
        rows = rows[: args.top]

    recv_u = result.receive_currency.upper()
    send_u = result.send_currency.upper()
    amt = result.send_amount

    if args.json:
        payload = providers_from_result(result, top=args.top)
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    print(f"url={result.url}")
    print(
        f"corridor={result.from_country}->{result.to_country} "
        f"{send_u}->{recv_u} amount={amt:g}"
    )
    print(f"providers={len(result.providers)} (list_rows_with_logo≈{result.provider_row_count})")
    for i, row in enumerate(rows, start=1):
        rate = row.receive_max / amt if amt else 0.0
        print(
            f"{i}. {row.label} ({row.slug}) — {row.receive_max:,} {recv_u} "
            f"(~{rate:,.4f} {recv_u}/{send_u} for {amt:g} {send_u})"
        )
    if args.timings:
        print("timing_s:", result.timing_s)


if __name__ == "__main__":
    main()
