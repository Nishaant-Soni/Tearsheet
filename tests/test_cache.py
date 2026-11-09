import anyio
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


# ---- addendum A4: cleanup


async def value_loader(v):
    return v


@pytest.mark.anyio
async def test_expired_entries_are_swept_on_next_set():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    cache.set("short", 1, ttl=10)
    cache.set("long", 2, ttl=100)
    clock.now = 50
    assert len(cache) == 2  # nothing removes "short" until the next write
    cache.set("new", 3, ttl=10)
    assert set(cache._entries) == {"long", "new"}


@pytest.mark.anyio
async def test_locks_do_not_outgrow_live_keys():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    for i in range(100):
        await cache.get_or_load(f"k{i}", 10, lambda i=i: value_loader(i))
    assert len(cache._locks) == len(cache) == 100
    clock.now = 11  # all expired
    await cache.get_or_load("fresh", 10, lambda: value_loader("x"))
    assert set(cache._entries) == {"fresh"}
    assert set(cache._locks) <= set(cache._entries)


@pytest.mark.anyio
async def test_failed_loads_leave_no_locks():
    cache = TTLCache()

    async def boom():
        raise RuntimeError("upstream down")

    for i in range(20):
        with pytest.raises(RuntimeError):
            await cache.get_or_load(f"bad{i}", 10, boom)
    assert cache._locks == {} and len(cache) == 0


@pytest.mark.anyio
async def test_concurrent_loads_still_share_one_fetch():
    cache = TTLCache()
    calls = 0
    started = anyio.Event()

    async def slow():
        nonlocal calls
        calls += 1
        started.set()
        await anyio.sleep(0.05)
        return "v"

    results = []

    async def request():
        results.append(await cache.get_or_load("k", 60, slow))

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(request)
        await started.wait()
        # Loads in flight: their lock must survive cleanup triggered by other writes.
        cache.set("other", 1, ttl=60)
        assert "k" in cache._locks
    assert calls == 1 and results == ["v"] * 5
    assert set(cache._locks) <= set(cache._entries)


def test_max_entries_evicts_closest_to_expiry():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    total = 256 + 10
    for i in range(total):
        cache.set(f"k{i}", i, ttl=1000 + i)  # k0 expires first, k265 last
    assert len(cache) == 256
    assert set(cache._entries) == {f"k{i}" for i in range(10, total)}


def test_max_entries_is_configurable_and_validated():
    cache = TTLCache(max_entries=3)
    for i in range(5):
        cache.set(i, i, ttl=10 + i)
    assert set(cache._entries) == {2, 3, 4}
    with pytest.raises(ValueError):
        TTLCache(max_entries=0)
