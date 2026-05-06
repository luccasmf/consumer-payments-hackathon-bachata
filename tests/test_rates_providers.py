"""Tests for FX rate providers and the multi-provider aggregator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services import rates_providers
from app.services.monito_compare import MonitoCompareResult, ProviderRow
from app.services.rates_providers import (
    FelixPagoPublicProvider,
    FxProvider,
    OpenErApiProvider,
    fetch_all_quotes,
    fetch_monito_quotes,
)
from app.services.rates_providers.base import FxProviderResult


def _mock_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Provider-level tests
# ---------------------------------------------------------------------------


class TestOpenErApiProvider:
    SAMPLE: dict[str, Any] = {
        "result": "success",
        "base_code": "USD",
        "rates": {"USD": 1.0, "MXN": 17.05, "COP": 3925.4},
    }

    def test_fetch_returns_rates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "open.er-api.com"
            return httpx.Response(200, json=self.SAMPLE)

        async def run() -> FxProviderResult:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                return await OpenErApiProvider().fetch_result(client=c)

        result = asyncio.run(run())

        assert result.provider == "open.er-api"
        assert result.base == "USD"
        assert result.rates["MXN"] == pytest.approx(17.05)
        assert result.source_url == "https://open.er-api.com"
        # The reference / base provider is open.er-api.
        assert result.is_base is True

    def test_raises_on_http_error(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        async def run() -> None:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                await OpenErApiProvider().fetch_result(client=c)

        with pytest.raises(httpx.HTTPError):
            asyncio.run(run())

    def test_raises_value_error_on_malformed_payload(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "error"})

        async def run() -> None:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                await OpenErApiProvider().fetch_result(client=c)

        with pytest.raises(ValueError):
            asyncio.run(run())


class _FakeMonitoService:
    """Test double for ``MonitoPlaywrightService``: returns a canned result."""

    def __init__(
        self,
        *,
        result: MonitoCompareResult | None = None,
        exception: Exception | None = None,
    ) -> None:
        self._result = result
        self._exception = exception
        self.calls: list[tuple[str, float, str | None]] = []

    async def fetch_raw(
        self,
        destination_country: str,
        amount: int | float,
        *,
        receive_currency: str | None = None,
        url: str | None = None,
    ) -> MonitoCompareResult:
        self.calls.append((destination_country, float(amount), receive_currency))
        if self._exception is not None:
            raise self._exception
        assert self._result is not None
        return self._result


def _make_monito_result(
    *,
    rows: list[tuple[str, str, int]],
    receive_currency: str = "mxn",
    send_amount: float = 250.0,
) -> MonitoCompareResult:
    return MonitoCompareResult(
        url="https://www.monito.com/en/compare/transfer/us/mx/usd/mxn/250",
        headless=True,
        from_country="us",
        to_country="mx",
        send_currency="usd",
        receive_currency=receive_currency,
        send_amount=send_amount,
        providers=tuple(
            ProviderRow(slug=slug, label=label, receive_max=amount)
            for slug, label, amount in rows
        ),
        timing_s={},
        receive_amount_regex_hits=0,
        provider_row_count=len(rows),
    )


class TestFetchMonitoQuotes:
    def test_each_row_becomes_its_own_result(self) -> None:
        result = _make_monito_result(
            rows=[
                ("remitly", "Remitly", 4_280),
                ("wise", "Wise", 4_277),
                ("western-union", "Western Union", 4_250),
            ],
            send_amount=250.0,
        )
        service = _FakeMonitoService(result=result)

        results = asyncio.run(
            fetch_monito_quotes("mx", 250.0, "MXN", service=service)
        )

        assert [r.provider for r in results] == [
            "Remitly",
            "Wise",
            "Western Union",
        ]
        # Rate per USD is receive_max / amount.
        assert results[0].rates["MXN"] == pytest.approx(4_280 / 250)
        assert results[0].base == "USD"
        # Source URL points back to the Monito comparison page so the user
        # could click through if surfaced in the UI.
        assert results[0].source_url is not None
        assert "monito.com" in results[0].source_url
        # No Monito row is the project's reference / base provider.
        assert all(r.is_base is False for r in results)
        # Service was invoked with the right corridor + receive currency.
        assert service.calls == [("mx", 250.0, "mxn")]

    def test_returns_empty_on_missing_country(self) -> None:
        service = _FakeMonitoService(
            result=_make_monito_result(rows=[("remitly", "Remitly", 100)])
        )

        results = asyncio.run(
            fetch_monito_quotes(None, 250.0, "MXN", service=service)
        )

        assert results == []
        assert service.calls == []

    def test_returns_empty_on_zero_amount(self) -> None:
        service = _FakeMonitoService(
            result=_make_monito_result(rows=[("remitly", "Remitly", 100)])
        )

        results = asyncio.run(
            fetch_monito_quotes("mx", 0.0, "MXN", service=service)
        )

        assert results == []
        assert service.calls == []

    def test_swallows_scraping_exceptions(self) -> None:
        service = _FakeMonitoService(exception=RuntimeError("playwright crashed"))

        results = asyncio.run(
            fetch_monito_quotes("mx", 250.0, "MXN", service=service)
        )

        assert results == []

    def test_skips_rows_with_zero_or_missing_amount(self) -> None:
        result = _make_monito_result(
            rows=[
                ("remitly", "Remitly", 4_280),
                ("blank", "", 4_000),  # missing label → skip
                ("zero", "Zero Receive", 0),  # zero receive_max → skip
            ],
        )
        service = _FakeMonitoService(result=result)

        results = asyncio.run(
            fetch_monito_quotes("mx", 250.0, "MXN", service=service)
        )

        assert [r.provider for r in results] == ["Remitly"]


class TestFelixPagoPublicProvider:
    SAMPLE: dict[str, Any] = {
        "USD": {"base": "1"},
        "MXN": {"base": "16.99", "tradfi_fv": "17.26"},
        "BRL": {"tradfi_fv": "4.95"},
        "COP": {"base": "3667.95", "tradfi_fv": "3735.63"},
    }

    def test_fetch_prefers_base_then_tradfi_fv(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "us-central1-felix-tech-production.cloudfunctions.net"
            assert "/all_rates_public" in str(request.url)
            return httpx.Response(200, json=self.SAMPLE)

        async def run() -> FxProviderResult:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                return await FelixPagoPublicProvider().fetch_result(client=c)

        result = asyncio.run(run())

        assert result.provider == "felixpago.com"
        assert result.is_base is False
        assert result.rates["USD"] == pytest.approx(1.0)
        assert result.rates["MXN"] == pytest.approx(16.99)
        assert result.rates["BRL"] == pytest.approx(4.95)
        assert result.rates["COP"] == pytest.approx(3667.95)

    @pytest.mark.parametrize(
        "bad_json",
        [
            [],
            {"XX": {"base": "1"}},  # invalid code → empty rates
        ],
    )
    def test_raises_value_error_on_unusable_payload(self, bad_json: Any) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=bad_json)

        async def run() -> None:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                await FelixPagoPublicProvider().fetch_result(client=c)

        with pytest.raises(ValueError):
            asyncio.run(run())


# ---------------------------------------------------------------------------
# Aggregator tests
# ---------------------------------------------------------------------------


class _StaticProvider(FxProvider):
    """Test double — returns canned rates without any HTTP."""

    def __init__(
        self, name: str, rates: dict[str, float], should_fail: Exception | None = None
    ) -> None:
        self.name = name
        self.source_url = f"https://example.test/{name}"
        self.base = "USD"
        self._rates = rates
        self._should_fail = should_fail

    async def fetch(self, client: httpx.AsyncClient) -> dict[str, float]:
        if self._should_fail is not None:
            raise self._should_fail
        return dict(self._rates)


class TestFetchAllQuotes:
    def test_aggregates_all_successful_providers(self) -> None:
        providers = [
            _StaticProvider("alpha", {"MXN": 17.0}),
            _StaticProvider("beta", {"MXN": 17.5}),
        ]
        results = asyncio.run(fetch_all_quotes(providers=providers))

        assert [r.provider for r in results] == ["alpha", "beta"]
        assert results[0].rates["MXN"] == 17.0
        assert results[1].rates["MXN"] == 17.5

    def test_drops_failing_providers_silently(self) -> None:
        providers = [
            _StaticProvider("alpha", {"MXN": 17.0}),
            _StaticProvider(
                "broken", {}, should_fail=httpx.ConnectError("nope")
            ),
            _StaticProvider("gamma", {"MXN": 17.2}),
        ]
        results = asyncio.run(fetch_all_quotes(providers=providers))

        assert [r.provider for r in results] == ["alpha", "gamma"]

    def test_returns_empty_list_when_all_fail(self) -> None:
        providers = [
            _StaticProvider("a", {}, should_fail=httpx.ConnectError("nope")),
            _StaticProvider("b", {}, should_fail=ValueError("malformed")),
        ]
        results = asyncio.run(fetch_all_quotes(providers=providers))

        assert results == []

    def test_base_provider_is_open_er_api_and_first(self) -> None:
        # BASE_PROVIDER and the head of the registry must be the same
        # OpenErApiProvider instance so anything anchoring on "results[0]"
        # matches anything anchoring on BASE_PROVIDER.
        assert rates_providers.BASE_PROVIDER is rates_providers.PROVIDERS[0]
        assert isinstance(rates_providers.BASE_PROVIDER, OpenErApiProvider)
        assert rates_providers.BASE_PROVIDER.is_base is True
        # And the secondary providers don't claim to be base.
        for provider in rates_providers.PROVIDERS[1:]:
            assert provider.is_base is False

    def test_default_uses_module_providers_list(self) -> None:
        # The rate-table registry holds the HTTP providers only — Monito
        # (per-corridor multi-provider scrape) is stitched in at the
        # service layer because it needs ``(country, amount)`` upfront.
        assert isinstance(rates_providers.PROVIDERS, list)
        assert len(rates_providers.PROVIDERS) >= 2
        assert all(isinstance(p, FxProvider) for p in rates_providers.PROVIDERS)
