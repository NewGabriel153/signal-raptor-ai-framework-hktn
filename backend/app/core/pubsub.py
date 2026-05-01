from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.config import settings


_pubsub_redis: Redis | None = None
_pubsub_lock = asyncio.Lock()


def get_session_event_channel(session_id: UUID | str) -> str:
    return f"session:{session_id}:events"


async def get_pubsub_redis() -> Redis:
    global _pubsub_redis

    if _pubsub_redis is not None:
        return _pubsub_redis

    async with _pubsub_lock:
        if _pubsub_redis is None:
            _pubsub_redis = Redis.from_url(
                settings.redis_dsn,
                encoding="utf-8",
                decode_responses=True,
            )

    return _pubsub_redis


async def close_pubsub_redis() -> None:
    global _pubsub_redis

    if _pubsub_redis is None:
        return

    await _pubsub_redis.aclose()
    _pubsub_redis = None


async def ping_pubsub_redis() -> bool:
    redis = await get_pubsub_redis()
    return bool(await redis.ping())


async def publish_session_event(session_id: UUID | str, event: dict[str, Any]) -> int:
    redis = await get_pubsub_redis()
    payload = json.dumps(event, separators=(",", ":"))
    return int(await redis.publish(get_session_event_channel(session_id), payload))


async def create_session_pubsub(session_id: UUID | str) -> PubSub:
    redis = await get_pubsub_redis()
    channel = get_session_event_channel(session_id)
    pubsub: PubSub = redis.pubsub()
    await pubsub.subscribe(channel)

    return pubsub


async def close_session_pubsub(session_id: UUID | str, pubsub: PubSub) -> None:
    channel = get_session_event_channel(session_id)
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()


async def iter_session_events(pubsub: PubSub) -> AsyncGenerator[dict[str, Any], None]:
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue

        raw_payload = message.get("data")
        if not isinstance(raw_payload, str):
            continue

        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            yield payload


async def subscribe_session_events(session_id: UUID | str) -> AsyncGenerator[dict[str, Any], None]:
    pubsub = await create_session_pubsub(session_id)

    try:
        async for payload in iter_session_events(pubsub):
            yield payload
    finally:
        await close_session_pubsub(session_id, pubsub)