"""Tests for the historical FX fetch + QuickChart URL builder."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import rates_history


def _mock_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _date_from_request(request: httpx.Request) -> str:
    """Extract the dated tag from a fawazahmed0 currency-api URL."""
    match = re.search(r"currency-api@(\d{4}-\d{2}-\d{2})/", str(request.url))
    assert match is not None, f"unexpected URL: {request.url}"
    return match.group(1)


# ---------------------------------------------------------------------------
# fetch_recent_history
# ---------------------------------------------------------------------------


class TestFetchRecentHistory:
    TODAY = dt.date(2026, 5, 6)

    def _payload(self, rate: float) -> dict[str, Any]:
        return {"date": "ignored", "usd": {"mxn": rate, "brl": rate / 3}}

    def test_returns_iso_keyed_history_in_ascending_order(self) -> None:
        # Map each requested date to a slightly different rate so we can
        # verify ordering by date (not by request order).
        rate_by_date = {
            (self.TODAY - dt.timedelta(days=i)).isoformat(): 17.0 + i * 0.1
            for i in range(5)
        }

        def handler(request: httpx.Request) -> httpx.Response:
            rate = rate_by_date[_date_from_request(request)]
            return httpx.Response(200, json=self._payload(rate))

        async def run() -> dict[str, float]:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                return await rates_history.fetch_recent_history(
                    "MXN", days=5, today=self.TODAY, client=c
                )

        history = asyncio.run(run())

        assert list(history.keys()) == sorted(history.keys())
        assert len(history) == 5
        # Oldest day was requested for i=4 → rate 17.4; newest was i=0 → 17.0.
        assert history[(self.TODAY - dt.timedelta(days=4)).isoformat()] == pytest.approx(17.4)
        assert history[self.TODAY.isoformat()] == pytest.approx(17.0)

    def test_drops_days_that_fail_silently(self) -> None:
        ok_date = self.TODAY.isoformat()

        def handler(request: httpx.Request) -> httpx.Response:
            if _date_from_request(request) == ok_date:
                return httpx.Response(200, json=self._payload(17.0))
            return httpx.Response(500, text="boom")

        async def run() -> dict[str, float]:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                return await rates_history.fetch_recent_history(
                    "MXN", days=5, today=self.TODAY, client=c
                )

        history = asyncio.run(run())

        assert history == {ok_date: pytest.approx(17.0)}

    def test_drops_currency_missing_from_payload(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"date": "x", "usd": {"brl": 5.1}})

        async def run() -> dict[str, float]:
            async with httpx.AsyncClient(transport=_mock_transport(handler)) as c:
                return await rates_history.fetch_recent_history(
                    "MXN", days=3, today=self.TODAY, client=c
                )

        assert asyncio.run(run()) == {}

    def test_zero_days_returns_empty(self) -> None:
        async def run() -> dict[str, float]:
            return await rates_history.fetch_recent_history("MXN", days=0)

        assert asyncio.run(run()) == {}


# ---------------------------------------------------------------------------
# build_chart_url
# ---------------------------------------------------------------------------


class TestBuildChartUrl:
    HISTORY = {
        "2026-05-02": 17.0,
        "2026-05-03": 17.1,
        "2026-05-04": 17.2,
        "2026-05-05": 17.05,
        "2026-05-06": 17.08,
    }

    def test_returns_none_for_empty_history(self) -> None:
        assert rates_history.build_chart_url("MXN", {}) is None

    def test_builds_quickchart_url_with_encoded_chart_config(self) -> None:
        url = rates_history.build_chart_url("MXN", self.HISTORY)
        assert url is not None

        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "quickchart.io"
        assert parsed.path == "/chart"

        params = parse_qs(parsed.query)
        assert "c" in params
        config = json.loads(params["c"][0])

        assert config["type"] == "line"
        assert config["data"]["labels"] == list(self.HISTORY.keys())
        assert config["data"]["datasets"][0]["data"] == list(self.HISTORY.values())
        assert "USD → MXN" in config["data"]["datasets"][0]["label"]
        # QuickChart sizing/background defaults made it through the query.
        assert params["w"] == ["600"]
        assert params["h"] == ["320"]

    def test_custom_title_overrides_default(self) -> None:
        url = rates_history.build_chart_url(
            "MXN", self.HISTORY, title="Custom title here"
        )
        assert url is not None
        config = json.loads(parse_qs(urlparse(url).query)["c"][0])
        assert config["options"]["title"]["text"] == "Custom title here"


# ---------------------------------------------------------------------------
# get_history_chart_url (composition)
# ---------------------------------------------------------------------------


class TestGetHistoryChartUrl:
    def test_returns_url_when_history_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(*_: Any, **__: Any) -> dict[str, float]:
            return {"2026-05-06": 17.0, "2026-05-07": 17.1}

        monkeypatch.setattr(rates_history, "fetch_recent_history", fake_fetch)

        url = asyncio.run(rates_history.get_history_chart_url("MXN"))
        assert url is not None
        assert "quickchart.io" in url

    def test_returns_none_when_history_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(*_: Any, **__: Any) -> dict[str, float]:
            return {}

        monkeypatch.setattr(rates_history, "fetch_recent_history", fake_fetch)

        assert asyncio.run(rates_history.get_history_chart_url("MXN")) is None

    def test_returns_none_when_pipeline_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(*_: Any, **__: Any) -> dict[str, float]:
            raise httpx.ConnectError("network down")

        monkeypatch.setattr(rates_history, "fetch_recent_history", fake_fetch)

        assert asyncio.run(rates_history.get_history_chart_url("MXN")) is None
