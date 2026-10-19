import pytest

from filecache_sim import LRUFileCache, SimulatedDisk


@pytest.fixture
def disk():
    d = SimulatedDisk()
    d.write("a", "a" * 40)
    d.write("b", "b" * 50)
    d.write("c", "c" * 60)
    d.reset_counters()
    return d


@pytest.fixture
def cache(disk):
    return LRUFileCache(120, disk)


def test_invalid_capacity(disk):
    with pytest.raises(ValueError):
        LRUFileCache(0, disk)


def test_miss_then_hit(cache, disk):
    assert cache.read("a") == "a" * 40
    assert cache.read("a") == "a" * 40
    assert (cache.stats.misses, cache.stats.hits) == (1, 1)
    assert disk.reads == 1


def test_read_missing_file(cache):
    assert cache.read("nope") is None
    assert cache.stats.misses == 1
    assert len(cache) == 0


def test_recency_order(cache):
    cache.read("a")
    cache.read("b")
    cache.read("a")
    assert cache.keys() == ["a", "b"]  # MRU -> LRU


def test_evicts_least_recently_used(cache):
    cache.read("a")
    cache.read("b")
    cache.read("a")      # b is now LRU
    cache.read("c")      # needs 60B, only 30 free -> evict b
    assert "b" not in cache
    assert cache.keys() == ["c", "a"]
    assert cache.stats.evictions == 1


def test_evicts_multiple_for_large_file(cache):
    cache.read("a")      # 40
    cache.read("b")      # 90
    cache.write("big", "x" * 110)   # must evict both a and b
    assert cache.keys() == ["big"]
    assert cache.stats.evictions == 2
    assert cache.used_bytes == 110


def test_write_is_deferred_until_eviction(cache, disk):
    cache.write("new", "hello")
    assert cache.is_dirty("new")
    assert disk.writes == 0            # write-back: nothing hit the disk yet
    cache.read("c")
    cache.read("b")                    # 5 + 60 + 50 = 115, still fits
    cache.read("a")                    # forces eviction of "new" (LRU)
    assert "new" not in cache
    assert disk.writes == 1
    assert disk.read("new") == "hello"
    assert cache.stats.write_backs == 1


def test_flush_cleans_dirty(cache, disk):
    cache.write("new", "hello")
    cache.flush()
    assert not cache.is_dirty("new")
    assert disk.read("new") == "hello"
    assert cache.stats.write_backs == 1


def test_overwrite_updates_size(cache):
    cache.write("f", "x" * 30)
    cache.write("f", "y" * 10)
    assert cache.used_bytes == 10
    assert len(cache) == 1
    assert cache.read("f") == "y" * 10


def test_oversized_file_bypasses_cache(cache, disk):
    cache.write("huge", "h" * 500)
    assert "huge" not in cache
    assert disk.read("huge") == "h" * 500


def test_delete_removes_from_cache_and_disk(cache, disk):
    cache.read("a")
    cache.delete("a")
    assert "a" not in cache
    assert not disk.exists("a")
    assert cache.used_bytes == 0


def test_events_emitted(disk):
    events = []
    c = LRUFileCache(120, disk, on_event=events.append)
    c.read("a")
    c.read("a")
    assert any("MISS" in e for e in events)
    assert any("HIT" in e for e in events)


def test_hit_ratio(cache):
    cache.read("a")
    cache.read("a")
    cache.read("a")
    assert cache.stats.hit_ratio == pytest.approx(2 / 3)
