"""Fixed-window per-user rate limiting for expensive endpoints.

Uses Redis when reachable (shared across API instances); falls back to an in-process counter
so local development without Redis still works.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

import redis

from .config import get_settings
from .errors import ApiError

log = logging.getLogger("slipslopes.ratelimit")
_local: dict[str, int] = defaultdict(int)
_lock = threading.Lock()
_redis: redis.Redis | None = None
_redis_checked = 0.0


def _client() -> redis.Redis | None:
    global _redis, _redis_checked
    if _redis is not None or time.time() - _redis_checked < 30:
        return _redis
    _redis_checked = time.time()
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        client.ping()
        _redis = client
    except redis.RedisError:
        log.info("rate limiter using in-process counters (Redis unavailable)")
        _redis = None
    return _redis


def check_rate(user_id: str, bucket: str, limit: int, window_s: int) -> None:
    if limit <= 0:
        return
    window = int(time.time() // window_s)
    key = f"rl:{bucket}:{user_id}:{window}"
    client = _client()
    count: int
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_s + 5)
            count = int(pipe.execute()[0])
        except redis.RedisError:
            client = None
    if client is None:
        with _lock:
            _local[key] += 1
            count = _local[key]
    if count > limit:
        retry = window_s - int(time.time()) % window_s
        raise ApiError(429, "rate_limited", f"Too many requests. Try again in {retry} seconds.",
                       headers={"Retry-After": str(retry)})


def reset_local() -> None:
    """Tests only."""
    with _lock:
        _local.clear()
