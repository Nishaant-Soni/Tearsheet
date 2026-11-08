import pandas as pd
import pytest

from tearsheet.data.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.anyio
async def test_hit_returns_equal_independent_copy():
    cache = TTLCache()
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return pd.DataFrame({"close": [1.0, 2.0]})

    first = await cache.get_or_load("k", 60, load)
    first.loc[0, "close"] = 999.0  # caller mutation must not leak into the cache
    second = await cache.get_or_load("k", 60, load)
    third = await cache.get_or_load("k", 60, load)

    assert calls == 1
    assert second["close"].tolist() == [1.0, 2.0]
    pd.testing.assert_frame_equal(second, third)
    assert second is not third


@pytest.mark.anyio
async def test_entries_expire():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        return [calls]

    assert await cache.get_or_load("k", 10, load) == [1]
    clock.now = 9.9
    assert await cache.get_or_load("k", 10, load) == [1]
    clock.now = 10.0
    assert await cache.get_or_load("k", 10, load) == [2]


@pytest.mark.anyio
async def test_failed_load_is_not_cached():
    cache = TTLCache()
    attempts = 0

    async def load():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        await cache.get_or_load("k", 60, load)
    assert await cache.get_or_load("k", 60, load) == "ok"
