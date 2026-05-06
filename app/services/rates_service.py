"""
FX rates conversation flow.

Two-turn conversation:

1. User asks for rates → bot prompts for *country* and *amount*.
2. User replies with both (or sends them in the original message) →
   bot returns conversions from every available FX provider so the user
   can compare quotes side by side.

Provider implementations live in :mod:`app.services.rates_providers`.

Quotes for the same (currency, USD amount) are cached in Redis for five minutes
when Redis is configured; the structured payload includes a UTC timestamp for
freshness. When a quote is produced we additionally attach a 7-day USD→<currency>
trend chart (anchored on the base provider) so the user gets a single
WhatsApp message with the comparison + visual.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.schemas.fx_comparison import FxComparisonResponse, FxProviderQuote
from app.services.rates_history import get_history_chart_url
from app.services.rates_providers import (
    FxProviderResult,
    fetch_all_quotes,
    fetch_monito_quotes,
)
from app.services.redis_client import RedisStorageClient, get_redis_storage_client

logger = logging.getLogger(__name__)

FX_QUOTE_CACHE_TTL_SECONDS = 300

# Canonical spot / chart anchor (see ``OpenErApiProvider``). Internal id matches
# ``OpenErApiProvider.name``; users see :data:`DEFAULT_FX_PROVIDER_DISPLAY_NAME` instead.
DEFAULT_FX_PROVIDER_NAME = "open.er-api"
DEFAULT_FX_PROVIDER_DISPLAY_NAME = "General exchange price"


@dataclass(frozen=True)
class RatesReply:
    """Structured reply from the rates flow.

    ``body`` is always set (the text the bot will say). ``chart_url``
    is populated only when we successfully built a 7-day trend chart for
    the requested currency — the bot then sends ``body`` as the image
    caption instead of as a standalone text message.
    """

    body: str
    chart_url: str | None = None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _comparison_cache_key(currency_code: str, amount_usd: float) -> str:
    normalized = f"{round(amount_usd, 2):.2f}"
    return f"fx:comparison:{currency_code}:{normalized}"


def _comparison_is_fresh(
    timestamp: datetime,
    *,
    max_age_seconds: int = FX_QUOTE_CACHE_TTL_SECONDS,
) -> bool:
    now = datetime.now(UTC)
    ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    return (now - ts) < timedelta(seconds=max_age_seconds)


# ---------------------------------------------------------------------------
# Comparison build + render
# ---------------------------------------------------------------------------


def build_fx_comparison_from_providers(
    destination_country: str,
    currency_code: str,
    amount_usd: float,
    results: list[FxProviderResult],
    *,
    timestamp: datetime | None = None,
) -> FxComparisonResponse | None:
    """Build a structured comparison from raw provider results (ordered like ``results``).

    Carries ``is_base`` through onto each :class:`FxProviderQuote`. Best quote /
    spread metrics apply to **remittance** providers only (excluding the default
    spot feed: :data:`DEFAULT_FX_PROVIDER_NAME`).
    """
    quotes: list[FxProviderQuote] = []
    ts = timestamp or datetime.now(UTC)
    for result in results:
        if currency_code not in result.rates:
            continue
        rate = result.rates[currency_code]
        quotes.append(
            FxProviderQuote(
                provider=result.provider,
                total_received=amount_usd * rate,
                rate_per_usd=rate,
                is_base=result.is_base,
            )
        )
    if not quotes:
        return None

    remittance = [q for q in quotes if q.provider != DEFAULT_FX_PROVIDER_NAME]
    best_remittance = (
        max(remittance, key=lambda q: q.total_received) if remittance else None
    )
    spread_rate: float | None = None
    advantage: float | None = None
    if len(remittance) > 1:
        rates_only = [q.rate_per_usd for q in remittance]
        spread_rate = max(rates_only) - min(rates_only)
        advantage = amount_usd * spread_rate

    return FxComparisonResponse(
        destination_country=destination_country,
        currency_code=currency_code,
        amount_usd=amount_usd,
        quotes=quotes,
        best_provider=best_remittance.provider if best_remittance else None,
        spread_rate=spread_rate,
        advantage_vs_worst=advantage,
        timestamp=ts,
    )


def _provider_display_name(provider: str) -> str:
    """User-facing label; the base spot feed is not branded as the upstream API name."""
    if provider == DEFAULT_FX_PROVIDER_NAME:
        return DEFAULT_FX_PROVIDER_DISPLAY_NAME
    return provider


def _rank_number_emoji(index: int) -> str:
    """1️⃣ … 🔟 for the first ten rows; plain digits after that."""
    glyphs = (
        "1️⃣",
        "2️⃣",
        "3️⃣",
        "4️⃣",
        "5️⃣",
        "6️⃣",
        "7️⃣",
        "8️⃣",
        "9️⃣",
        "🔟",
    )
    if index < len(glyphs):
        return glyphs[index]
    return f"{index + 1}."


def _quick_pick_bullets(
    response: FxComparisonResponse,
    ranked_remittance: list[FxProviderQuote],
) -> list[str]:
    """2–3 English bullets aligned with the product doc (priorities / picks).

    ``ranked_remittance`` is remittance-only (excludes the default spot quote).
    """
    if not ranked_remittance:
        return [
            f"• *{DEFAULT_FX_PROVIDER_DISPLAY_NAME}* is the mid-market reference — "
            "no remittance quotes came back for this corridor."
        ]

    lines_out: list[str] = [
        f"• *Most {response.currency_code} received*: "
        f"{_provider_display_name(ranked_remittance[0].provider)}",
    ]
    if len(ranked_remittance) >= 2:
        lines_out.append(
            f"• *Next best*: {_provider_display_name(ranked_remittance[1].provider)}"
        )
    if len(lines_out) < 3 and len(ranked_remittance) >= 3:
        third = ranked_remittance[2]
        lines_out.append(f"• *Also competitive*: {_provider_display_name(third.provider)}")
    elif len(lines_out) < 3:
        felix_q = next(
            (q for q in ranked_remittance if "felix" in q.provider.lower()),
            None,
        )
        top_names = {
            ranked_remittance[i].provider for i in range(min(2, len(ranked_remittance)))
        }
        if felix_q is not None and felix_q.provider not in top_names:
            lines_out.append(
                f"• *On WhatsApp*: {_provider_display_name(felix_q.provider)}"
            )
    return lines_out[:3]


def format_comparison_response(
    response: FxComparisonResponse,
    *,
    from_cache: bool = False,
) -> str:
    """Render WhatsApp body text from a structured comparison.

    English layout aligned with ``docs/FX Rate Comparison API.md``: intro,
    optional default spot line (:data:`DEFAULT_FX_PROVIDER_DISPLAY_NAME`),
    numbered remittance rows (best→worst), explicit worst remittance callout,
    quick picks, and best-vs-worst gap among remittance quotes; trailing UTC
    timestamp.
    """
    if not response.quotes:
        return (
            f"I couldn't find a live rate for {response.destination_country} "
            f"({response.currency_code}) from any provider right now. Try again in a moment."
        )

    reference_q = next(
        (q for q in response.quotes if q.provider == DEFAULT_FX_PROVIDER_NAME),
        None,
    )
    remittance = [
        q for q in response.quotes if q.provider != DEFAULT_FX_PROVIDER_NAME
    ]
    ranked_remittance = sorted(
        remittance,
        key=lambda q: q.total_received,
        reverse=True,
    )

    lines = [
        (
            f"Today *${response.amount_usd:,.2f} USD* to "
            f"*{response.destination_country}* (*{response.currency_code}*) "
            f"converts like this — all-in, no surprises:"
        ),
        "",
    ]

    if reference_q:
        lines.append(
            f"*{DEFAULT_FX_PROVIDER_DISPLAY_NAME}* → "
            f"*{reference_q.total_received:,.2f} {response.currency_code}* "
            "— mid-market reference (chart)"
        )
        lines.append("")

    if ranked_remittance:
        lines.append("*Remittance estimates*")
        lines.append("")
        for i, quote in enumerate(ranked_remittance):
            prefix = _rank_number_emoji(i)
            lines.append(
                f"{prefix} *{quote.provider}* → "
                f"*{quote.total_received:,.2f} {response.currency_code}* "
                "— all-in estimate"
            )

    if len(ranked_remittance) >= 2:
        worst = ranked_remittance[-1]
        lines.append("")
        lines.append(
            f"⚠️ *{worst.provider}* delivers the least today — "
            f"*{worst.total_received:,.2f} {response.currency_code}* "
            "for this send amount."
        )

    lines.append("")
    lines.append("*What works best for you?*")
    lines.extend(_quick_pick_bullets(response, ranked_remittance))

    if len(ranked_remittance) >= 2:
        best = ranked_remittance[0]
        worst = ranked_remittance[-1]
        diff = best.total_received - worst.total_received
        lines.append("")
        lines.append(
            f"The difference between the best and worst is "
            f"*{diff:,.2f} {response.currency_code}* per "
            f"*{response.amount_usd:,.2f} USD* you send."
        )

    ts = response.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    cache_note = " (cached)" if from_cache else ""
    lines.append("")
    lines.append(f"_Updated {ts.strftime('%Y-%m-%d %H:%M')} UTC{cache_note}_")

    return "\n".join(lines)


async def _try_load_cached_comparison(
    redis: RedisStorageClient,
    currency_code: str,
    amount_usd: float,
) -> FxComparisonResponse | None:
    key = _comparison_cache_key(currency_code, amount_usd)
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        model = FxComparisonResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.debug("Invalid FX cache entry for %s: %s", key, exc)
        await redis.delete(key)
        return None
    if not _comparison_is_fresh(model.timestamp):
        await redis.delete(key)
        return None
    return model


async def _save_comparison_cache(
    redis: RedisStorageClient,
    currency_code: str,
    amount_usd: float,
    response: FxComparisonResponse,
) -> None:
    key = _comparison_cache_key(currency_code, amount_usd)
    await redis.delete(key)
    await redis.save(
        key,
        response.model_dump(mode="json"),
        ttl_seconds=FX_QUOTE_CACHE_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# Conversation parsing / state
# ---------------------------------------------------------------------------


# Currencies surfaced as featured corridors. Order matters for the prompt.
# (code, display_name, flag)
_FEATURED_CORRIDORS: list[tuple[str, str, str]] = [
    ("MXN", "Mexico", "🇲🇽"),
    ("COP", "Colombia", "🇨🇴"),
    ("GTQ", "Guatemala", "🇬🇹"),
    ("HNL", "Honduras", "🇭🇳"),
    ("DOP", "Dominican Republic", "🇩🇴"),
    ("BRL", "Brazil", "🇧🇷"),
]

# Triggers in English + Spanish that route a message to this service.
_RATE_KEYWORDS: tuple[str, ...] = (
    "rate",
    "rates",
    "fx",
    "exchange",
    "tasa",
    "tasas",
    "cambio",
    "tipo de cambio",
    "cotizacion",
    "cotización",
)

# Country / currency aliases → ISO 4217 currency code + display name.
# Keep keys lowercase. Hand-rolled (no `pycountry`) to stay dependency-light
# and to cover the LatAm corridors we actually care about.
_COUNTRY_ALIASES: dict[str, tuple[str, str]] = {
    # Mexico
    "mexico": ("MXN", "Mexico"),
    "méxico": ("MXN", "Mexico"),
    "mx": ("MXN", "Mexico"),
    "mxn": ("MXN", "Mexico"),
    # Colombia
    "colombia": ("COP", "Colombia"),
    "co": ("COP", "Colombia"),
    "cop": ("COP", "Colombia"),
    # Guatemala
    "guatemala": ("GTQ", "Guatemala"),
    "gt": ("GTQ", "Guatemala"),
    "gtq": ("GTQ", "Guatemala"),
    # Honduras
    "honduras": ("HNL", "Honduras"),
    "hn": ("HNL", "Honduras"),
    "hnl": ("HNL", "Honduras"),
    # Dominican Republic
    "dominican": ("DOP", "Dominican Republic"),
    "dominicana": ("DOP", "Dominican Republic"),
    "republica dominicana": ("DOP", "Dominican Republic"),
    "república dominicana": ("DOP", "Dominican Republic"),
    "dr": ("DOP", "Dominican Republic"),
    "do": ("DOP", "Dominican Republic"),
    "dop": ("DOP", "Dominican Republic"),
    # Brazil
    "brazil": ("BRL", "Brazil"),
    "brasil": ("BRL", "Brazil"),
    "br": ("BRL", "Brazil"),
    "brl": ("BRL", "Brazil"),
}

# Currency → ISO 3166-1 alpha-2 country code, used to drive the per-corridor
# Monito scrape. Only currencies present here will get Monito enrichment;
# other currencies fall back to the rate-table providers only.
_CURRENCY_TO_ISO2: dict[str, str] = {
    "MXN": "mx",
    "COP": "co",
    "GTQ": "gt",
    "HNL": "hn",
    "DOP": "do",
    "BRL": "br",
}


# Per-phone-number partial state: keeps whatever pieces of the rates
# request the user has supplied so far so we don't lose ``country`` after
# they answer the "and how much?" follow-up. In-process only — fine for
# the hackathon's single Uvicorn worker; swap for Redis/a state store if
# we ever scale out.
@dataclass
class _PendingRates:
    country: tuple[str, str] | None = None
    amount: float | None = None


_pending_rates: dict[str, _PendingRates] = {}


def is_rates_request(text: str | None) -> bool:
    """True if the inbound text looks like a request for FX rates."""
    if not text:
        return False
    lowered = text.lower().strip()
    return any(kw in lowered for kw in _RATE_KEYWORDS)


def is_awaiting_rates_input(phone: str) -> bool:
    """True if we previously prompted this phone for country + amount."""
    return phone in _pending_rates


def _get_pending(phone: str) -> _PendingRates:
    """Return (and create if missing) the pending state for ``phone``."""
    return _pending_rates.setdefault(phone, _PendingRates())


def _mark_pending(phone: str) -> _PendingRates:
    """Ensure a pending entry exists; returns the (possibly new) record."""
    return _get_pending(phone)


def _clear_pending(phone: str) -> None:
    _pending_rates.pop(phone, None)


def parse_country_and_amount(
    text: str | None,
) -> tuple[tuple[str, str] | None, float | None]:
    """
    Extract ``((currency_code, display_name), amount)`` from free-form text.

    Either side can be ``None`` if not found. Examples that parse:
    ``"Mexico 250"``, ``"$100 to Brazil"``, ``"send 1500 cop"``,
    ``"BRL 50.5"``, ``"100,5 mxn"``.
    """
    if not text:
        return None, None

    lowered = text.lower()

    country: tuple[str, str] | None = None
    # Longer aliases first so "republica dominicana" wins over "do".
    for alias in sorted(_COUNTRY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            country = _COUNTRY_ALIASES[alias]
            break

    amount: float | None = None
    # Match the first number, allowing thousands separators and either
    # ``.`` or ``,`` as decimal separator (Spanish-speakers often use ``,``).
    number_match = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+)([.,]\d+)?", lowered)
    if number_match:
        whole = number_match.group(1).replace(".", "").replace(",", "")
        decimal = number_match.group(2)
        try:
            if decimal:
                amount = float(f"{whole}.{decimal[1:]}")
            else:
                amount = float(whole)
        except ValueError:
            amount = None

    return country, amount


def get_rates_prompt() -> str:
    """Reply asking the user for the destination country and the USD amount."""
    countries = ", ".join(country for _, country, _ in _FEATURED_CORRIDORS[:4])
    return (
        "💱 Sure! To quote an exchange rate I need two things:\n"
        "1️⃣ The destination *country* (e.g. " + countries + ")\n"
        "2️⃣ The *amount* in USD (e.g. 250)\n\n"
        '_Example: "Mexico 250"_'
    )


def format_quote_message(
    country: str,
    code: str,
    amount: float,
    results: list[FxProviderResult],
) -> str:
    """Render a multi-provider conversion reply.

    Thin wrapper that builds an :class:`FxComparisonResponse` from the raw
    provider results and delegates to :func:`format_comparison_response`.
    """
    comparison = build_fx_comparison_from_providers(country, code, amount, results)
    if comparison is None:
        return (
            f"I couldn't find a live rate for {country} ({code}) from any "
            "provider right now. Try again in a moment."
        )
    return format_comparison_response(comparison, from_cache=False)


def format_missing_input_message(has_country: bool, has_amount: bool) -> str:
    """Reply that lists which piece(s) are still missing."""
    if not has_country and not has_amount:
        return get_rates_prompt()
    if not has_country:
        return (
            "Got the amount 👍 — which *country* should I convert to?\n"
            "_Example: Mexico, Colombia, Brazil…_"
        )
    return (
        "Got the country 👍 — how much in *USD* would you like to send?\n"
        '_Example: "250"_'
    )


def _chart_title_for(code: str) -> str:
    return (
        f"USD → {code} • last 7 days ({DEFAULT_FX_PROVIDER_DISPLAY_NAME})"
    )


def _chart_attachment_footer(currency_code: str) -> str:
    """Appended to the quote when a 7-day trend image is sent with the same reply."""
    return (
        "\n\n📊 _The graph shows *USD→"
        f"{currency_code}* over the *last 7 days* "
        f"(mid-market baseline / {DEFAULT_FX_PROVIDER_DISPLAY_NAME})._"
    )


async def handle_rates_message(phone: str, text: str | None) -> RatesReply:
    """
    Drive the multi-turn rates conversation.

    Call this whenever ``is_rates_request(text)`` matches OR the phone is
    already in ``is_awaiting_rates_input``. New ``country`` / ``amount``
    values from the latest message are *merged* into any state we already
    collected so the user can supply them across separate messages
    ("Mexico" → "250") without us re-asking for the first piece.

    Returns a :class:`RatesReply`. When a quote is produced (cache hit
    or miss) we also attempt to build a 7-day trend chart anchored on
    the base provider's currency and surface its URL — the bot sends the
    image with the quote text as caption.
    """
    new_country, new_amount = parse_country_and_amount(text)

    pending = _get_pending(phone)
    if new_country is not None:
        pending.country = new_country
    if new_amount is not None:
        pending.amount = new_amount

    if pending.country and pending.amount is not None:
        country, amount = pending.country, pending.amount
        _clear_pending(phone)
        code, display = country

        redis = get_redis_storage_client()
        if redis is not None:
            cached = await _try_load_cached_comparison(redis, code, amount)
            if cached is not None:
                body = format_comparison_response(cached, from_cache=True)
                chart_url = await get_history_chart_url(
                    code, title=_chart_title_for(code)
                )
                if chart_url:
                    body += _chart_attachment_footer(code)
                return RatesReply(body=body, chart_url=chart_url)

        # Run rate-table providers (open.er-api) and Monito (per-corridor
        # multi-provider scrape) in parallel. Each Monito row comes back
        # as its own FxProviderResult so individual remittance services
        # (Remitly, Wise, Western Union, …) sit alongside open.er-api in
        # the side-by-side reply.
        country_iso2 = _CURRENCY_TO_ISO2.get(code)
        api_results, monito_results = await asyncio.gather(
            fetch_all_quotes(),
            fetch_monito_quotes(country_iso2, amount, code),
        )
        results = [*api_results, *monito_results]
        if not results:
            return RatesReply(
                body=(
                    "Sorry — I couldn't reach any FX provider right now. "
                    "Please try again in a moment."
                )
            )

        comparison = build_fx_comparison_from_providers(display, code, amount, results)
        if comparison is None:
            return RatesReply(
                body=(
                    f"I couldn't find a live rate for {display} ({code}) from any "
                    "provider right now. Try again in a moment."
                )
            )

        if redis is not None:
            await _save_comparison_cache(redis, code, amount, comparison)

        body = format_comparison_response(comparison, from_cache=False)
        chart_url = await get_history_chart_url(code, title=_chart_title_for(code))
        if chart_url:
            body += _chart_attachment_footer(code)
        return RatesReply(body=body, chart_url=chart_url)

    return RatesReply(
        body=format_missing_input_message(
            has_country=pending.country is not None,
            has_amount=pending.amount is not None,
        )
    )
