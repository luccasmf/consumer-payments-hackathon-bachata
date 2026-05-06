"""Structured FX comparison payload (multi-provider quote for a USD send amount)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class FxProviderQuote(BaseModel):
    """One provider's conversion for a fixed USD amount."""

    provider: str = Field(description="Provider display name")
    total_received: float = Field(description="Destination currency received for amount_usd")
    rate_per_usd: float = Field(description="Destination units per 1 USD")
    is_base: bool = Field(
        default=False,
        description="True if this quote came from the project's reference / base provider",
    )


class FxComparisonResponse(BaseModel):
    """Side-by-side comparison for one corridor and amount, with cache-friendly metadata."""

    destination_country: str
    currency_code: str
    amount_usd: float
    quotes: list[FxProviderQuote] = Field(default_factory=list)
    best_provider: str | None = Field(
        default=None,
        description=(
            "Best remittance provider (highest total_received among non–open.er-api quotes); "
            "None if only the default FX feed is available."
        ),
    )
    spread_rate: float | None = Field(
        default=None,
        description=(
            "Among remittance quotes only: max(rate_per_usd) − min(rate_per_usd) when "
            "two or more remittance quotes exist"
        ),
    )
    advantage_vs_worst: float | None = Field(
        default=None,
        description="Extra destination currency vs worst remittance (amount_usd × spread_rate)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this comparison was produced (UTC); used for cache freshness",
    )
