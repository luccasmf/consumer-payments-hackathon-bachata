"""Async Upstash Redis REST client for simple key/value storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from upstash_redis.asyncio import Redis

from app.config import Settings, get_settings


def _utc_iso_timestamp() -> str:
    """UTC instant as ISO-8601 string with ``Z`` suffix (e.g. ``2026-05-06T12:00:00.123456Z``)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class RedisStorageClient:
    """Thin async wrapper around Upstash Redis REST for save/delete operations."""

    def __init__(self, url: str, token: str) -> None:
        if not url or not token:
            msg = "REDIS_URL and REDIS_TOKEN must both be set to use RedisStorageClient"
            raise ValueError(msg)
        self._redis = Redis(url=url, token=token)

    async def save(
        self,
        key: str,
        value: str | int | float | bool | dict[str, Any] | list[Any],
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store a value under ``key``. Dicts/lists are JSON-encoded."""
        if isinstance(value, (dict, list)):
            payload: str | int | float | bool = json.dumps(value)
        elif isinstance(value, (str, int, float, bool)):
            payload = value
        else:
            payload = str(value)
        kwargs: dict[str, int] = {}
        if ttl_seconds is not None:
            kwargs["ex"] = ttl_seconds
        await self._redis.set(key, payload, **kwargs)

    async def save_dict(
        self,
        key: str,
        data: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
        timestamp_key: str = "saved_at",
    ) -> dict[str, Any]:
        """Store a dictionary and merge a UTC ISO timestamp (overwrites same key if present).

        Returns the document actually written (including the timestamp field).
        """
        doc: dict[str, Any] = {**data, timestamp_key: _utc_iso_timestamp()}
        await self.save(key, doc, ttl_seconds=ttl_seconds)
        return doc

    async def delete(self, *keys: str) -> int:
        """Remove one or more keys. Returns the number of keys removed."""
        if not keys:
            return 0
        return int(await self._redis.delete(*keys))


def get_redis_storage_client(settings: Settings | None = None) -> RedisStorageClient | None:
    """Build a client from settings, or ``None`` if Redis is not configured."""
    s = settings or get_settings()
    if not s.redis_url or not s.redis_token:
        return None
    return RedisStorageClient(url=s.redis_url, token=s.redis_token)
