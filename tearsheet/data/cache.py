"""In-process TTL cache for price histories and financial statements.

`functools.lru_cache` cannot wrap async loaders, so this is a small dict-based cache.
A per-key lock makes concurrent requests for the same key share one upstream fetch.
Values are copied on the way in and out, so callers can never mutate a cached frame.
"""

import copy
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

import anyio
import pandas as pd

INTRADAY_TTL = 15 * 60
DAILY_TTL = 4 * 60 * 60
STATEMENT_TTL = 6 * 60 * 60


def _copy(value: Any) -> Any:
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.copy(deep=True)
    return copy.deepcopy(value)


class TTLCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[Hashable, tuple[float, Any]] = {}
        self._locks: dict[Hashable, anyio.Lock] = {}

    def get(self, key: Hashable) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        return _copy(value)

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        self._entries[key] = (self._clock() + ttl, _copy(value))

    async def get_or_load(
        self, key: Hashable, ttl: float, loader: Callable[[], Awaitable[Any]]
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(key, anyio.Lock())
        async with lock:
            cached = self.get(key)
            if cached is not None:
                return cached
            value = await loader()
            self.set(key, value, ttl)
            return _copy(value)

    def clear(self) -> None:
        self._entries.clear()
        self._locks.clear()
