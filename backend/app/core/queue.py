from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings


def get_redis_settings() -> RedisSettings:
    parsed = urlparse(settings.redis_dsn)

    return RedisSettings(
        host=parsed.hostname or settings.REDIS_HOST,
        port=parsed.port or settings.REDIS_PORT,
        database=int(parsed.path.lstrip("/") or settings.REDIS_DB),
        password=parsed.password or settings.REDIS_PASSWORD,
        ssl=parsed.scheme == "rediss",
    )


async def create_queue_pool() -> ArqRedis:
    return await create_pool(get_redis_settings())


async def close_queue_pool(redis: ArqRedis) -> None:
    if hasattr(redis, "aclose"):
        await redis.aclose(close_connection_pool=True)
        return

    await redis.close(close_connection_pool=True)