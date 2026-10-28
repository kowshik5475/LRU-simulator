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



def test_negative_capacity_is_rejected(disk):
    with pytest.raises(ValueError, match="positive"):
        LRUFileCache(-1, disk)


def test_non_integer_capacity_is_rejected(disk):
    with pytest.raises(TypeError, match="integer"):
        LRUFileCache(1.5, disk)


def test_unicode_capacity_uses_utf8_bytes(disk):
    cache = LRUFileCache(8, disk)
    cache.write("unicode", "é🙂")
    assert cache.entries()[0].size == len("é🙂".encode("utf-8")) == 6
    assert cache.used_bytes == 6
    cache.write("other", "abc")
    assert cache.used_bytes == 3
    assert cache.keys() == ["other"]
    assert disk.read("unicode") == "é🙂"


def test_content_exactly_equal_to_capacity_is_cached(disk):
    cache = LRUFileCache(4, disk)
    cache.write("exact", "éé")
    assert cache.keys() == ["exact"]
    assert cache.used_bytes == 4
    assert cache.is_dirty("exact")


def test_empty_content_is_cached_and_flushes_once(disk):
    cache = LRUFileCache(10, disk)
    cache.write("empty", "")
    assert cache.keys() == ["empty"]
    assert cache.used_bytes == 0
    assert cache.is_dirty("empty")
    cache.flush()
    assert not cache.is_dirty("empty")
    assert disk.read("empty") == ""
    writes_after_first_flush = disk.writes
    cache.flush()
    assert disk.writes == writes_after_first_flush


def test_overwrite_dirty_entry_persists_latest_content(cache, disk):
    cache.write("file", "old")
    cache.write("file", "new content")
    assert cache.used_bytes == len("new content".encode("utf-8"))
    assert len(cache) == 1
    assert cache.is_dirty("file")
    cache.flush()
    assert disk.read("file") == "new content"
    assert cache.stats.write_backs == 1


def test_overwriting_with_oversized_content_bypasses_and_does_not_leave_stale_entry(cache, disk):
    cache.write("file", "small")
    cache.write("file", "x" * 121)
    assert "file" not in cache
    assert cache.used_bytes == 0
    assert disk.read("file") == "x" * 121
    cache.flush()
    assert disk.read("file") == "x" * 121


def test_dirty_lru_eviction_writes_latest_content(cache, disk):
    cache.write("dirty", "D" * 30)
    cache.read("a")
    cache.read("b")
    cache.read("c")
    # The dirty entry is least-recently-used and must be persisted on eviction.
    cache.read("dirty")
    cache.write("large", "L" * 100)
    assert "dirty" not in cache
    assert disk.read("dirty") == "D" * 30
    assert cache.stats.write_backs >= 1
    assert cache.used_bytes <= cache.capacity_bytes


def test_delete_dirty_entry_does_not_resurrect_on_flush(cache, disk):
    cache.write("gone", "pending")
    cache.delete("gone")
    cache.flush()
    assert not disk.exists("gone")
    assert "gone" not in cache
    assert cache.used_bytes == 0


def test_oversized_read_is_returned_but_not_cached(disk):
    disk.write("huge", "é" * 61)  # 122 UTF-8 bytes
    disk.reset_counters()
    cache = LRUFileCache(120, disk)
    assert cache.read("huge") == "é" * 61
    assert "huge" not in cache
    assert cache.used_bytes == 0
    assert disk.reads == 1


def test_repeated_delete_is_safe(cache, disk):
    cache.read("a")
    cache.delete("a")
    cache.delete("a")
    assert "a" not in cache
    assert not disk.exists("a")
    assert cache.used_bytes == 0


def test_event_callback_failure_does_not_break_cache(disk):
    def broken_callback(_message):
        raise RuntimeError("observer failure")

    cache = LRUFileCache(10, disk, on_event=broken_callback)
    cache.write("a", "12345")
    cache.write("b", "67890")
    cache.read("a")
    assert cache.keys() == ["a", "b"]
    assert cache.used_bytes == 10


def test_invalid_content_type_is_rejected_without_corrupting_cache(cache):
    with pytest.raises(TypeError, match="content"):
        cache.write("bad", 123)  # type: ignore[arg-type]
    assert "bad" not in cache
    assert cache.used_bytes == 0


def test_cache_byte_accounting_matches_entries_after_mutations(cache):
    cache.write("a", "é" * 10)
    cache.write("b", "🙂" * 5)
    cache.read("c")
    cache.write("d", "z" * 80)
    assert cache.used_bytes == sum(entry.size for entry in cache.entries())
    assert cache.used_bytes <= cache.capacity_bytes
    assert len(cache.keys()) == len(set(cache.keys())) == len(cache)
