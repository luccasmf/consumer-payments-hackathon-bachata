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


def _make_result(name: str, rates: dict[str, float]) -> FxProviderResult:
    return FxProviderResult(
        provider=name,
        base="USD",
        rates=rates,
        source_url=f"https://example.test/{name}",
    )


SAMPLE_RESULTS: list[FxProviderResult] = [
    _make_result(
        "open.er-api",
        {"USD": 1.0, "MXN": 17.0512, "COP": 3925.4, "BRL": 5.12},
    ),
    _make_result(
        "exchangerate-api",
        {"USD": 1.0, "MXN": 17.1100, "COP": 3920.0, "BRL": 5.15},
    ),
]


@pytest.fixture(autouse=True)
def _reset_pending_state() -> None:
    """Make sure no test leaks pending-rates flags into others."""
    rates_service._pending_rates.clear()
    yield
    rates_service._pending_rates.clear()


@pytest.fixture(autouse=True)
def _disable_redis_cache(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real Redis from `.env` except in :class:`TestFxRedisCache` (explicit mocks)."""
    if request.node.get_closest_marker("redis_cache") or "TestFxRedisCache" in request.node.nodeid:
        return
    monkeypatch.setattr(
        rates_service,
        "get_redis_storage_client",
        lambda *_a, **_k: None,
    )


def _stub_fetch_all(
    monkeypatch: pytest.MonkeyPatch, results: list[FxProviderResult]
) -> None:
    async def fake(*_: Any, **__: Any) -> list[FxProviderResult]:
        return list(results)

    monkeypatch.setattr(rates_service, "fetch_all_quotes", fake)


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

        assert "Quote — Mexico" in message
        assert "250.00 USD" in message
        # Both providers and both conversion totals show up.
        assert "open.er-api" in message
        assert "exchangerate-api" in message
        # 250 * 17.0512 = 4262.80 ; 250 * 17.11 = 4277.50
        assert "4,262.80" in message
        assert "4,277.50" in message
        # Spread shown when 2+ providers present.
        assert "Spread" in message
        assert "2026-05-06 16:44" in message

    def test_highlights_the_best_rate(self) -> None:
        message = rates_service.format_quote_message(
            "Mexico", "MXN", 250.0, SAMPLE_RESULTS
        )
        lines = message.splitlines()

        provider_lines = [line for line in lines if line.startswith("• ")]
        # 17.11 > 17.0512 → exchangerate-api should be on top with the badge.
        assert "exchangerate-api" in provider_lines[0]
        assert "🏆" in provider_lines[0]
        assert "BEST" in provider_lines[0]
        assert "open.er-api" in provider_lines[1]
        assert "🏆" not in provider_lines[1]

        # Summary line with savings vs. worst quote.
        # extra = 250 * (17.1100 - 17.0512) = 14.70
        assert "Best deal" in message
        assert "exchangerate-api" in message
        assert "14.70" in message

    def test_skips_providers_missing_target_currency(self) -> None:
        partial = [
            _make_result("alpha", {"MXN": 17.0}),
            _make_result("beta", {"BRL": 5.0}),  # no MXN
        ]
        message = rates_service.format_quote_message("Mexico", "MXN", 100.0, partial)

        assert "alpha" in message
        assert "beta" not in message
        # With only one quote remaining we shouldn't print spread/best-deal lines.
        assert "Spread" not in message
        assert "Best deal" not in message
        # And there's no badge to award when there's nothing to compare.
        assert "🏆" not in message

    def test_returns_friendly_message_when_no_provider_has_currency(self) -> None:
        none_match = [_make_result("alpha", {"BRL": 5.0})]
        message = rates_service.format_quote_message("Mexico", "MXN", 100.0, none_match)

        assert "couldn't find" in message.lower()


class TestHandleRatesMessage:
    PHONE = "+15551234567"

    def test_initial_request_prompts_for_inputs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates"))

        assert "country" in reply.lower()
        assert "amount" in reply.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

    def test_followup_with_country_and_amount_returns_multi_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "Mexico" in reply
        assert "open.er-api" in reply
        assert "exchangerate-api" in reply
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_one_shot_message_with_keyword_country_and_amount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "rates Brazil 100")
        )

        assert "Brazil" in reply
        assert "BRL" in reply
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_followup_missing_amount_reprompts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "Mexico"))

        assert "USD" in reply
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

    def test_followup_missing_country_reprompts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "250"))

        assert "country" in reply.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

    def test_split_turns_country_then_amount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """User sends country first, then the amount in a separate message."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        # Turn 1: trigger.
        asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates"))
        # Turn 2: country only.
        reply2 = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico")
        )
        assert "USD" in reply2  # asks for the amount
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

        # Turn 3: amount only — must NOT re-ask for the country.
        reply3 = asyncio.run(rates_service.handle_rates_message(self.PHONE, "250"))
        assert "Quote — Mexico" in reply3
        assert "MXN" in reply3
        assert "open.er-api" in reply3
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_split_turns_amount_then_country(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same scenario in the opposite order — amount first, then country."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates"))

        reply2 = asyncio.run(rates_service.handle_rates_message(self.PHONE, "250"))
        assert "country" in reply2.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is True

        reply3 = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico")
        )
        assert "Quote — Mexico" in reply3
        assert "250.00 USD" in reply3
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_new_value_overrides_previous_pending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the user changes their mind mid-flow we use the latest value."""
        _stub_fetch_all(monkeypatch, SAMPLE_RESULTS)

        asyncio.run(rates_service.handle_rates_message(self.PHONE, "rates Mexico"))
        # User changes the country before specifying the amount.
        asyncio.run(rates_service.handle_rates_message(self.PHONE, "Brazil"))
        reply = asyncio.run(rates_service.handle_rates_message(self.PHONE, "100"))

        assert "Quote — Brazil" in reply
        assert "Mexico" not in reply
        assert "BRL" in reply

    def test_returns_friendly_error_when_all_providers_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, [])
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "couldn't reach" in reply.lower()
        assert rates_service.is_awaiting_rates_input(self.PHONE) is False

    def test_partial_provider_failure_still_quotes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only one provider responded; the reply should still render.
        _stub_fetch_all(monkeypatch, [SAMPLE_RESULTS[0]])
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "open.er-api" in reply
        assert "exchangerate-api" not in reply
        assert "Spread" not in reply

    def test_handles_unsupported_currency_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_fetch_all(monkeypatch, [_make_result("alpha", {"USD": 1.0})])
        rates_service._mark_pending(self.PHONE)

        reply = asyncio.run(
            rates_service.handle_rates_message(self.PHONE, "Mexico 250")
        )

        assert "couldn't find" in reply.lower()


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
        assert "(cached)" in reply
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
