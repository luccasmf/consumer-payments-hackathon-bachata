"""Unit tests for RedisStorageClient (mocked; no Upstash network calls)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.services.redis_client import RedisStorageClient, get_redis_storage_client


class TestRedisStorageClient:
    @pytest.mark.parametrize(
        ("value", "expected_payload"),
        [
            ("plain", "plain"),
            (42, 42),
            (True, True),
            ({"a": 1}, '{"a": 1}'),
            ([1, 2], "[1, 2]"),
        ],
    )
    def test_save_serializes_and_calls_set(
        self, value: object, expected_payload: str | int | bool
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.set = AsyncMock(return_value=None)

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> None:
            await client.save("k", value)  # type: ignore[arg-type]

        asyncio.run(_run())

        mock_redis.set.assert_awaited_once_with("k", expected_payload)

    def test_save_passes_ttl_when_given(self) -> None:
        mock_redis = MagicMock()
        mock_redis.set = AsyncMock(return_value=None)

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> None:
            await client.save("k", "v", ttl_seconds=60)

        asyncio.run(_run())

        mock_redis.set.assert_awaited_once_with("k", "v", ex=60)

    def test_get_returns_string_or_none(self) -> None:
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(side_effect=["value", None])

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> tuple[str | None, str | None]:
            first = await client.get("a")
            second = await client.get("b")
            return first, second

        assert asyncio.run(_run()) == ("value", None)

    def test_get_decodes_bytes(self) -> None:
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"bytes-value")

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> str | None:
            return await client.get("k")

        assert asyncio.run(_run()) == "bytes-value"

    @pytest.mark.parametrize(
        ("timestamp_key", "expected_ts_field"),
        [
            ("saved_at", "saved_at"),
            ("timestamp", "timestamp"),
        ],
    )
    def test_save_dict_merges_timestamp_and_returns_document(
        self, timestamp_key: str, expected_ts_field: str
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.set = AsyncMock(return_value=None)
        fixed_ts = "2026-05-06T15:30:00.000000Z"

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> dict[str, object]:
            with patch(
                "app.services.redis_client._utc_iso_timestamp",
                return_value=fixed_ts,
            ):
                return await client.save_dict(
                    "session:1",
                    {"user": "sam", "step": 2},
                    timestamp_key=timestamp_key,
                )

        doc = asyncio.run(_run())

        assert doc == {"user": "sam", "step": 2, expected_ts_field: fixed_ts}
        _key, payload = mock_redis.set.await_args.args
        assert _key == "session:1"
        assert json.loads(payload) == doc

    def test_save_dict_passes_ttl(self) -> None:
        mock_redis = MagicMock()
        mock_redis.set = AsyncMock(return_value=None)

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> None:
            with patch(
                "app.services.redis_client._utc_iso_timestamp",
                return_value="2026-05-06T15:30:00.000000Z",
            ):
                await client.save_dict("k", {"a": 1}, ttl_seconds=120)

        asyncio.run(_run())

        mock_redis.set.assert_awaited_once()
        assert mock_redis.set.await_args.kwargs == {"ex": 120}

    @pytest.mark.parametrize(
        ("keys", "mock_return", "expected"),
        [
            (("a",), 1, 1),
            (("a", "b"), 2, 2),
            ((), 0, 0),
        ],
    )
    def test_delete(
        self, keys: tuple[str, ...], mock_return: int, expected: int
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock(return_value=mock_return)

        with patch("app.services.redis_client.Redis", return_value=mock_redis):
            client = RedisStorageClient(url="https://example.upstash.io", token="t")

        async def _run() -> int:
            return await client.delete(*keys)

        assert asyncio.run(_run()) == expected
        if keys:
            mock_redis.delete.assert_awaited_once_with(*keys)
        else:
            mock_redis.delete.assert_not_called()


class TestGetRedisStorageClient:
    def test_returns_none_when_not_configured(self) -> None:
        settings = Settings.model_validate({"REDIS_URL": "", "REDIS_TOKEN": ""})
        assert get_redis_storage_client(settings) is None

    def test_returns_client_when_configured(self) -> None:
        settings = Settings.model_validate(
            {
                "REDIS_URL": "https://example.upstash.io",
                "REDIS_TOKEN": "secret",
            }
        )
        client = get_redis_storage_client(settings)
        assert isinstance(client, RedisStorageClient)
