"""In-process TTL cache for price histories and financial statements.

`functools.lru_cache` cannot wrap async loaders, so this is a small dict-based cache.
A per-key lock makes concurrent requests for the same key share one upstream fetch.
Values are copied on the way in and out, so callers can never mutate a cached frame.

The cache cleans up after itself: every `set` drops expired entries and locks that
no live entry or in-flight load needs, and at most `max_entries` entries are kept.
Eviction is least-recently-used, so a fresh short-lived entry (15-minute intraday)
is not thrown out just because it expires sooner than the daily entries around it.
"""

import copy
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

import anyio
import pandas as pd

INTRADAY_TTL = 15 * 60
DAILY_TTL = 4 * 60 * 60
STATEMENT_TTL = 6 * 60 * 60
MAX_ENTRIES = 256


def _copy(value: Any) -> Any:
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return value.copy(deep=True)
    return copy.deepcopy(value)


class TTLCache:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = MAX_ENTRIES,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._clock = clock
        self._max_entries = max_entries
        # Least recently used first.
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._locks: dict[Hashable, anyio.Lock] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: Hashable) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return _copy(value)

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        now = self._clock()
        for k in [
            k for k, (expires_at, _) in self._entries.items() if now >= expires_at
        ]:
            del self._entries[k]
        self._entries[key] = (now + ttl, _copy(value))
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)  # least recently used
        self._prune_locks()

    def _prune_locks(self) -> None:
        """Drop locks with no live entry and no task holding or waiting on them.

        anyio hands a released lock straight to the next waiter, so a lock that is
        unlocked with nobody waiting is safe to forget.
        """
        for k in [
            k
            for k, lock in self._locks.items()
            if k not in self._entries
            and not lock.locked()
            and lock.statistics().tasks_waiting == 0
        ]:
            del self._locks[k]

    async def get_or_load(
        self, key: Hashable, ttl: float, loader: Callable[[], Awaitable[Any]]
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(key, anyio.Lock())
        try:
            async with lock:
                cached = self.get(key)
                if cached is not None:
                    return cached
                value = await loader()
                self.set(key, value, ttl)
                return _copy(value)
        finally:
            # A failed load leaves no entry; forget its lock unless others use it.
            if (
                key not in self._entries
                and not lock.locked()
                and lock.statistics().tasks_waiting == 0
                and self._locks.get(key) is lock
            ):
                del self._locks[key]

    def clear(self) -> None:
        self._entries.clear()
        self._locks.clear()
