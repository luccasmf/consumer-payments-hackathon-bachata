"""
FX rates conversation flow.

Two-turn conversation:

1. User asks for rates → bot prompts for *country* and *amount*.
2. User replies with both (or sends them in the original message) →
   bot returns conversions from every available FX provider so the user
   can compare quotes side by side.

Provider implementations live in :mod:`app.services.rates_providers`.
"""

import logging
import re
from dataclasses import dataclass

from app.services.rates_providers import FxProviderResult, fetch_all_quotes

logger = logging.getLogger(__name__)

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

    Quotes are sorted best-first (highest target-currency-per-USD = the
    sender gets more local currency for the same USD), with the winning
    provider tagged ``🏆 BEST``. When 2+ providers respond we add a
    summary line showing how much extra the user pockets vs. the worst
    quote.
    """
    quotes: list[tuple[FxProviderResult, float]] = [
        (r, r.rates[code]) for r in results if code in r.rates
    ]

    if not quotes:
        return (
            f"I couldn't find a live rate for {country} ({code}) from any "
            "provider right now. Try again in a moment."
        )

    # Best rate = most local currency per USD for the sender.
    quotes.sort(key=lambda item: item[1], reverse=True)
    has_comparison = len(quotes) > 1
    best_result, best_rate = quotes[0]

    header = (
        "*Provider quotations* (best first):"
        if has_comparison
        else "*Provider quotation:*"
    )
    lines = [
        f"💱 *Quote — {country}*",
        f"Sending {amount:,.2f} USD",
        "",
        header,
    ]
    for index, (result, rate) in enumerate(quotes):
        converted = amount * rate
        # Only award the badge when there's something to compare against.
        badge = " 🏆 *BEST*" if has_comparison and index == 0 else ""
        lines.append(
            f"• *{result.provider}*: {converted:,.2f} {code} "
            f"_(1 USD = {rate:,.4f})_{badge}"
        )

    if has_comparison:
        _, worst_rate = quotes[-1]
        extra = amount * (best_rate - worst_rate)
        spread = best_rate - worst_rate
        lines.append("")
        lines.append(
            f"🏆 Best deal: *{best_result.provider}* — "
            f"you'd get *{extra:,.2f} {code}* more than the lowest quote."
        )
        lines.append(f"_Spread across providers: {spread:,.4f} {code}_")

    return "\n".join(lines)


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


async def handle_rates_message(phone: str, text: str | None) -> str:
    """
    Drive the multi-turn rates conversation.

    Call this whenever ``is_rates_request(text)`` matches OR the phone is
    already in ``is_awaiting_rates_input``. New ``country`` / ``amount``
    values from the latest message are *merged* into any state we already
    collected so the user can supply them across separate messages
    ("Mexico" → "250") without us re-asking for the first piece.
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
        results = await fetch_all_quotes()
        if not results:
            return (
                "Sorry — I couldn't reach any FX provider right now. "
                "Please try again in a moment."
            )
        code, display = country
        return format_quote_message(display, code, amount, results)

    return format_missing_input_message(
        has_country=pending.country is not None,
        has_amount=pending.amount is not None,
    )
