"""Tests for the rates conversation flow (orchestration over providers)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import rates_service
from app.services.rates_providers.base import FxProviderResult


def _make_result(
    name: str, rates: dict[str, float], *, is_base: bool = False
) -> FxProviderResult:
    return FxProviderResult(
        provider=name,
        base="USD",
        rates=rates,
        source_url=f"https://example.test/{name}",
        is_base=is_base,
    )


SAMPLE_RESULTS: list[FxProviderResult] = [
    _make_result(
        "open.er-api",
        {"USD": 1.0, "MXN": 17.0512, "COP": 3925.4, "BRL": 5.12},
        is_base=True,
    ),
    # Representative second provider — shape mirrors what
    # ``fetch_monito_quotes`` produces (single-currency rates dict, no
    # is_base). Named after a real Monito row for realism.
    _make_result(
        "Wise",
        {"MXN": 17.1100, "COP": 3920.0, "BRL": 5.15},
    ),
]

# Default + two remittance feeds so spread copy exercises the multi-remittance path.
THREE_REMITTANCE_RESULTS: list[FxProviderResult] = [
    SAMPLE_RESULTS[0],
    SAMPLE_RESULTS[1],
    _make_result("low-tier-api", {"USD": 1.0, "MXN": 17.0000, "COP": 3900.0}),
]


@pytest.fixture(autouse=True)
def _reset_pending_state() -> None:
    """Make sure no test leaks pending-rates flags into others."""
    rates_service._pending_rates.clear()
    yield
    rates_service._pending_rates.clear()


@pytest.fixture(autouse=True)
def _disable_redis_cache(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid real Redis from `.env` except in :class:`TestFxRedisCache` (explicit mocks)."""
    if (
        request.node.get_closest_marker("redis_cache")
        or "TestFxRedisCache" in request.node.nodeid
    ):
        return
    monkeypatch.setattr(
        rates_service,
        "get_redis_storage_client",
        lambda *_a, **_k: None,
    )


@pytest.fixture(autouse=True)
def _stub_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Default: pretend the chart pipeline returned nothing. Tests that
    actually want to assert chart-URL behavior override this with their
    own ``monkeypatch.setattr`` call (it wins because pytest applies the
    most-recent setattr last). Applies to all tests, including the
    Redis-cache class — chart fetching is independent of caching.
    """

    async def fake(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(rates_service, "get_history_chart_url", fake)


@pytest.fixture(autouse=True)
def _stub_monito(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Default: pretend Monito returned no rows. Real Monito calls drive a
    Chromium scrape and must never run in tests. Override per-test with
    :func:`_stub_monito_results` to inject canned rows.
    """

    async def fake(*_: Any, **__: Any) -> list[FxProviderResult]:
        return []

    monkeypatch.setattr(rates_service, "fetch_monito_quotes", fake)


def _stub_fetch_all(
    monkeypatch: pytest.MonkeyPatch, results: list[FxProviderResult]
) -> None:
    async def fake(*_: Any, **__: Any) -> list[FxProviderResult]:
        return list(results)

    monkeypatch.setattr(rates_service, "fetch_all_quotes", fake)


def _stub_monito_results(
    monkeypatch: pytest.MonkeyPatch, results: list[FxProviderResult]
) -> None:
    async def fake(*_: Any, **__: Any) -> list[FxProviderResult]:
        return list(results)

    monkeypatch.setattr(rates_service, "fetch_monito_quotes", fake)


def _stub_chart_url(monkeypatch: pytest.MonkeyPatch, url: str | None) -> None:
    async def fake(*_: Any, **__: Any) -> str | None:
        return url

    monkeypatch.setattr(rates_service, "get_history_chart_url", fake)


class TestIsRatesRequest:
    @pytest.mark.parametrize(
        "text",
        [
            "rate",
            "What are the rates today?",
            "Quiero saber la tasa",
            "Cuál es el tipo de cambio?",
            "cambio USD MXN",
            "fx please",
            "COTIZACION",
        ],
    )
    def test_matches_known_keywords(self, text: str) -> None:
        assert rates_service.is_rates_request(text) is True

    @pytest.mark.parametrize(
        "text",
        [None, "", "hello there", "send 100 dollars", "transfer money"],
    )
    def test_ignores_unrelated_text(self, text: str | None) -> None:
        assert rates_service.is_rates_request(text) is False


class TestParseCountryAndAmount:
    @pytest.mark.parametrize(
        "text, expected_code, expected_amount",
        [
            ("Mexico 250", "MXN", 250.0),
            ("send 100 to brazil", "BRL", 100.0),
            ("BRL 50.5", "BRL", 50.5),
            ("100,5 mxn", "MXN", 100.5),
            ("$1,000 to colombia", "COP", 1000.0),
            ("República Dominicana 75", "DOP", 75.0),
            ("guatemala", "GTQ", None),
            ("250", None, 250.0),
        ],
    )
    def test_parses_combinations(
        self, text: str, expected_code: str | None, expected_amount: float | None
    ) -> None:
        country, amount = rates_service.parse_country_and_amount(text)
        actual_code = country[0] if country else None
        assert actual_code == expected_code
        if expected_amount is None:
            assert amount is None
        else:
            assert amount == pytest.approx(expected_amount)

    def test_returns_none_for_empty_text(self) -> None:
        assert rates_service.parse_country_and_amount("") == (None, None)
        assert rates_service.parse_country_and_amount(None) == (None, None)


class TestFormatQuoteMessage:
    def test_renders_one_line_per_provider(self) -> None:
        fixed = datetime(2026, 5, 6, 16, 44, tzinfo=UTC)
        comparison = rates_service.build_fx_comparison_from_providers(
            "Mexico", "MXN", 250.0, SAMPLE_RESULTS, timestamp=fixed
        )
        assert comparison is not None
        message = rates_service.format_comparison_response(comparison)

        assert "Mexico" in message
        assert "you're sending" in message
        assert "250.00 USD" in message
        assert "4,262.80" in message
        assert "4,277.50" in message
        assert "open.er-api" in message
        assert "exchangerate-api" in message
        assert "Default FX rate" in message
        assert "Remittance provider rates" in message
        assert "Best FX:" in message
        assert "2026-05-06 16:44" in message

    @pytest.mark.parametrize(
        "results, expect_spread_line",
        [
            (SAMPLE_RESULTS, False),
            (THREE_REMITTANCE_RESULTS, True),
        ],
    )
    def test_spread_line_only_with_multiple_remittance_feeds(
        self,
        results: list[FxProviderResult],
        expect_spread_line: bool,
    ) -> None:
        message = rates_service.format_quote_message("Mexico", "MXN", 250.0, results)
        if expect_spread_line:
            assert "top remittance quote pays" in message
            # 250 * (17.11 - 17.00) = 27.50 MXN between best and worst remittance.
            assert "27.50" in message
        else:
            assert "top remittance quote pays" not in message

    def test_highlights_the_best_rate(self) -> None:
        message = rates_service.format_quote_message(
            "Mexico", "MXN", 250.0, SAMPLE_RESULTS
        )
        lines = message.splitlines()

        provider_lines = [line for line in lines if line.startswith("• ")]
        # Default spot block first; remittance list sorted best → worst (by total MXN).
        assert "open.er-api" in provider_lines[0]
        assert "4,262.80" in provider_lines[0]
        assert "exchangerate-api" in provider_lines[1]
        assert "4,277.50" in provider_lines[1]
        assert not any("🏆" in line for line in provider_lines)

        # Summary line names the winning provider and the savings vs. worst quote.
        # extra = 250 * (17.1100 - 17.0512) = 14.70
        assert "Wise" in message
        assert "pays about" in message
        assert "14.70" in message
        idx = lines.index("*Remittance provider rates (best → worst)*")
        assert lines[idx + 3].startswith("🏆 *Best FX:*")
        assert "exchangerate-api" in lines[idx + 3]

    def test_skips_providers_missing_target_currency(self) -> None:
        partial = [
            _make_result("alpha", {"MXN": 17.0}),
            _make_result("beta", {"BRL": 5.0}),  # no MXN
        ]
        message = rates_service.format_quote_message("Mexico", "MXN", 100.0, partial)

        assert "1,700.00" in message
        assert "alpha" in message
        assert "beta" not in message
        # One remittance quote → spread paragraph omitted; Best FX line still names the winner.
        assert "top remittance quote pays" not in message
        assert "🏆 *Best FX:* *alpha*" in message

    def test_returns_friendly_message_when_no_provider_has_currency(self) -> None:
        none_match = [_make_result("alpha", {"BRL": 5.0})]
        message = rates_service.format_quote_message("Mexico", "MXN", 100.0, none_match)

        assert "couldn't find" in message.lower()

    def test_labels_base_provider(self) -> None:
        message = rates_service.format_quote_message(
            "Mexico", "MXN", 250.0, SAMPLE_RESULTS
        )
        provider_lines = [line for line in message.splitlines() if line.startswith("• ")]

        # open.er-api is default spot → chart tag stays on that bullet only.
        base_line = next(line for line in provider_lines if "4,262.80" in line)
        secondary_line = next(line for line in provider_lines if "4,277.50" in line)
        assert "📍" in base_line
        assert "chart" in base_line
        assert "📍" not in secondary_line

    def test_default_spot_can_outrank_remittance_but_best_callout_is_remittance_only(
        self,
    ) -> None:
        # Stronger spot rate than the secondary remittance feed.
        results = [
            _make_result("open.er-api", {"MXN": 17.5}, is_base=True),
            _make_result("Wise", {"MXN": 17.0}),
        ]
        message = rates_service.format_quote_message("Mexico", "MXN", 100.0, results)
        default_line = next(
            line for line in message.splitlines()
            if line.startswith("• ") and "open.er-api" in line
        )
        assert "1,750.00" in default_line
        assert "chart" in default_line

        best_line = next(line for line in message.splitlines() if line.startswith("🏆 *Best FX:"))
        assert "exchangerate-api" in best_line
        assert "1,700.00" in best_line


class TestHandleRatesMessage:
    PHONE = "+15551234567"

    def test_initial_request_prompts_for_inputs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates"))

        assert reply.chart_url is None
        assert "country" in reply.body.lower()
        assert "amount" in reply.body.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

    def test_followup_with_country_and_amount_returns_multi_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "Mexico" in reply.body
        assert "open.er-api" in reply.body
        assert "Wise" in reply.body
        assert "4,262.80" in reply.body
        assert "4,277.50" in reply.body
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_one_shot_message_with_keyword_country_and_amount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "rates Brazil 100")
        )

        assert "Brazil" in reply.body
        assert "BRL" in reply.body
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_followup_missing_amount_reprompts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "Mexico"))

        assert "USD" in reply.body
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

    def test_followup_missing_country_reprompts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "250"))

        assert "country" in reply.body.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

    def test_split_turns_country_then_amount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """User sends country first, then the amount in a separate message."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates"))
        reply2 = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico")
        )
        assert "USD" in reply2.body
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

        reply3 = asyncio.run(rates_service.handle_rates_message(self.PHONE, "250"))
        assert "Mexico" in reply3.body
        assert "you're sending" in reply3.body
        assert "MXN" in reply3.body
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_split_turns_amount_then_country(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same scenario in the opposite order — amount first, then country."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates"))

        reply2 = asyncio.run(rates_service.handle_rates_message(self.PHONE, "250"))
        assert "country" in reply2.body.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

        reply3 = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico")
        )
        assert "Mexico" in reply3.body
        assert "250.00 USD" in reply3.body
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_new_value_overrides_previous_pending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the user changes their mind mid-flow we use the latest value."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates Mexico"))
        asyncio.run(rates_service.handle_rates_message(self.PHONE, "Brazil"))
        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "100"))

        assert "Brazil" in reply.body
        assert "Mexico" not in reply.body
        assert "BRL" in reply.body

    def test_returns_friendly_error_when_all_providers_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, [])
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "couldn't reach" in reply.body.lower()
        assert reply.chart_url is None
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_partial_provider_failure_still_quotes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, [SAMPLE_RESULTS[0]])
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "open.er-api" in reply.body
        assert "4,262.80" in reply.body
        assert "Wise" not in reply.body
        assert "4,277.50" not in reply.body
        # No comparison summary when only one provider responds.
        assert "top remittance quote pays" not in reply.body

    def test_handles_unsupported_currency_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, [_make_result("alpha", {"USD": 1.0})])
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "couldn't find" in reply.body.lower()

    def test_attaches_chart_url_when_history_pipeline_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        _stub_chart_url(monkeypatch, "https://quickchart.io/chart?c=...&w=600")
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert reply.chart_url == "https://quickchart.io/chart?c=...&w=600"
        assert "Mexico" in reply.body
        assert "you're sending" in reply.body

    def test_no_chart_url_when_history_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        _stub_chart_url(monkeypatch, None)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert reply.chart_url is None
        assert "Mexico" in reply.body
        assert "you're sending" in reply.body

    def test_merges_monito_rows_as_distinct_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Monito results are stitched in alongside the API providers.

        Each Monito row (Remitly, Wise, Western Union, …) becomes its own
        line in the reply with its own rate.
        """
        _stub_fetch_all(monkeypatch, [SAMPLE_RESULTS[0]])  # only open.er-api
        _stub_monito_results(
            monkeypatch,
            [
                _make_result("Remitly", {"MXN": 17.20}),
                _make_result("Wise", {"MXN": 17.15}),
                _make_result("Western Union", {"MXN": 16.90}),
            ],
        )
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        # All sources appear as distinct providers in the body.
        assert "open.er-api" in reply.body
        assert "Remitly" in reply.body
        assert "Wise" in reply.body
        assert "Western Union" in reply.body

        provider_lines = [
            line for line in reply.body.splitlines() if line.startswith("• ")
        ]
        assert len(provider_lines) == 4
        # Highest MXN-per-USD wins the BEST badge → Remitly at 17.20.
        assert "Remitly" in provider_lines[0]
        assert "best" in provider_lines[0]
        # Base flag still attaches to open.er-api regardless of ranking.
        base_line = next(line for line in provider_lines if "open.er-api" in line)
        assert "chart" in base_line

    def test_monito_passes_country_iso2_and_amount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The service maps currency code → ISO2 country before scraping."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        captured: list[tuple[Any, ...]] = []

        async def fake_monito(*args: Any, **kwargs: Any) -> list[FxProviderResult]:
            captured.append(args)
            return []

        monkeypatch.setattr(rates_service, "fetch_monito_quotes", fake_monito)
        rates_service._mark_pending(self.PHONE)

        asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Brazil 100")
        )

        assert captured == [("br", 100.0, "BRL")]


# Smoke test that an old import path doesn't accidentally come back.
def test_old_fetch_usd_rates_is_gone() -> None:
    assert not hasattr(rates_service, "fetch_usd_rates")
    assert not hasattr(rates_service, "RATES_URL")


@pytest.mark.redis_cache
class TestFxRedisCache:
    """Explicit Redis mocks — autouse does not stub ``get_redis_storage_client`` here."""

    PHONE = "+15559998888"

    def test_cache_hit_skips_provider_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        async def counting_fetch(*_: Any, **__: Any) -> list[FxProviderResult]:
            calls.append(1)
            return SAMPLE_RESULTS

        monkeypatch.setattr(rates_service, "fetch_all_quotes", counting_fetch)

        cached_model = rates_service.build_fx_comparison_from_providers(
            "Mexico", "MXN", 250.0, SAMPLE_RESULTS, timestamp=datetime.now(UTC)
        )
        assert cached_model is not None
        payload = json.dumps(cached_model.model_dump(mode="json"))

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=payload)
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.save = AsyncMock(return_value=None)

        monkeypatch.setattr(
            rates_service,
            "get_redis_storage_client",
            lambda *_a, **_k: mock_redis,
        )

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert calls == []
        assert "(cached)" in reply.body
        mock_redis.save.assert_not_called()

    def test_stale_cache_deleted_and_refetches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        async def counting_fetch(*_: Any, **__: Any) -> list[FxProviderResult]:
            calls.append(1)
            return SAMPLE_RESULTS

        monkeypatch.setattr(rates_service, "fetch_all_quotes", counting_fetch)

        old_ts = datetime.now(UTC) - timedelta(minutes=10)
        stale = rates_service.build_fx_comparison_from_providers(
            "Mexico", "MXN", 250.0, SAMPLE_RESULTS, timestamp=old_ts
        )
        assert stale is not None
        payload = json.dumps(stale.model_dump(mode="json"))

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=payload)
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.save = AsyncMock(return_value=None)

        monkeypatch.setattr(
            rates_service,
            "get_redis_storage_client",
            lambda *_a, **_k: mock_redis,
        )

        asyncio.run(rates_service.handle_rates_message(self.PHONE, "Mexico 250"))

        assert calls == [1]
        mock_redis.delete.assert_awaited()
        mock_redis.save.assert_awaited()


# Provider import is wired through the service via fetch_all_quotes.
def test_service_uses_aggregator_indirection() -> None:
    # Sanity: the module-level binding exists so monkeypatch works.
    assert callable(rates_service.fetch_all_quotes)
    # And it's the one from the providers package.
    from app.services.rates_providers import fetch_all_quotes as agg

    assert rates_service.fetch_all_quotes is agg
