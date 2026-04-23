from __future__ import annotations

import redis

from services.shared.settings import redis_url


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(redis_url(), decode_responses=True)
