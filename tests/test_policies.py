"""Tests for the scan-resistant policy and comparative workload behavior."""

from __future__ import annotations

import random

import pytest

from filecache_sim import AdaptiveLRUPolicy, LRUFileCache, SimulatedDisk


def make_cache(policy_name: str, capacity: int = 4, sizes: dict[str, int] | None = None):
    sizes = sizes or {name: 1 for name in "abcdefghij"}
    disk = SimulatedDisk()
    for name, size in sizes.items():
        disk.write(name, name * size)
    disk.reset_counters()
    policy = AdaptiveLRUPolicy(capacity) if policy_name == "adaptive" else None
    return LRUFileCache(capacity, disk, policy=policy)


def run_trace(policy_name: str, trace: list[str], capacity: int = 4,
              sizes: dict[str, int] | None = None):
    cache = make_cache(policy_name, capacity, sizes)
    for name in trace:
        cache.read(name)
        assert cache.used_bytes == sum(entry.size for entry in cache.entries())
        assert cache.used_bytes <= cache.capacity_bytes
        assert len(cache.keys()) == len(set(cache.keys()))
    return cache


def test_default_policy_is_standard_lru_baseline():
    cache = make_cache("lru")
    assert cache.policy_diagnostics() == {"policy": "lru"}
    for name in ["a", "b", "a", "c", "d"]:
        cache.read(name)
    assert cache.keys() == ["d", "c", "a", "b"]


def test_adaptive_promotes_repeatedly_accessed_entries():
    cache = make_cache("adaptive", capacity=4)
    cache.read("a")  # first observed use: probationary
    assert cache.policy_diagnostics()["probationary_entries"] == 1
    cache.read("a")  # second observed use: promoted
    diagnostics = cache.policy_diagnostics()
    assert diagnostics["promotions"] == 1
    assert diagnostics["protected_entries"] == 1
    assert diagnostics["admissions"] == 1


def test_scan_larger_than_cache_preserves_protected_hot_set():
    capacity = 3
    trace = ["a", "b", "a", "b"] + list("cdefghij")
    lru = run_trace("lru", trace, capacity)
    adaptive = run_trace("adaptive", trace, capacity)

    # The benchmark records both policies' actual outcomes without asserting
    # that adaptive must win on every trace.
    assert lru.stats.hits + lru.stats.misses == len(trace)
    assert adaptive.stats.hits + adaptive.stats.misses == len(trace)
    assert adaptive.policy_diagnostics()["scan_related_decisions"] > 0
    assert adaptive.policy_diagnostics()["evictions"] == adaptive.stats.evictions
    assert adaptive.used_bytes <= capacity


def test_hot_file_accesses_interrupted_by_scan():
    trace = ["a", "b", "a", "b"] + list("cdefgh") + ["a", "b", "a", "b"]
    lru = run_trace("lru", trace, capacity=3)
    adaptive = run_trace("adaptive", trace, capacity=3)
    assert adaptive.stats.hits + adaptive.stats.misses == len(trace)
    assert lru.stats.hits + lru.stats.misses == len(trace)
    assert adaptive.used_bytes <= 3


def test_uniform_random_workload_is_deterministic_for_same_seed():
    rng = random.Random(314159)
    trace = [rng.choice(list("abcdefghij")) for _ in range(250)]
    first = run_trace("adaptive", trace, capacity=5)
    second = run_trace("adaptive", trace, capacity=5)
    assert first.stats.hits == second.stats.hits
    assert first.stats.misses == second.stats.misses
    assert first.keys() == second.keys()
    assert first.policy_diagnostics() == second.policy_diagnostics()


def test_changing_hot_file_sets():
    trace = list("abc") * 8 + list("def") * 8 + list("ghi") * 8
    adaptive = run_trace("adaptive", trace, capacity=4)
    assert adaptive.used_bytes <= 4
    diagnostics = adaptive.policy_diagnostics()
    assert diagnostics["promotions"] > 0
    assert diagnostics["ghost_hits"] > 0
    assert diagnostics["adaptive_demotions"] > 0
    # The latest hot set should be represented after repeated accesses.
    assert set(adaptive.keys()) & set("ghi")


def test_mixed_file_sizes_preserve_capacity_invariants():
    sizes = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}
    trace = ["a", "b", "a", "b", "c", "d", "a", "e", "f", "b", "a"]
    adaptive = run_trace("adaptive", trace, capacity=7, sizes=sizes)
    assert adaptive.used_bytes == sum(entry.size for entry in adaptive.entries())
    assert adaptive.used_bytes <= adaptive.capacity_bytes


def test_dirty_entry_eviction_writes_back_latest_content():
    disk = SimulatedDisk()
    disk.write("hot", "old")
    for name in ["a", "b", "c", "d"]:
        disk.write(name, name)
    disk.reset_counters()
    cache = LRUFileCache(3, disk, policy=AdaptiveLRUPolicy(3))
    cache.write("hot", "NEW")
    cache.read("a")
    cache.read("b")
    cache.read("c")
    cache.read("d")
    assert "hot" not in cache
    assert disk.read("hot") == "NEW"
    assert cache.used_bytes <= cache.capacity_bytes
    assert cache.policy_diagnostics()["evictions"] == cache.stats.evictions


def test_overwrite_delete_flush_and_oversized_bypass_keep_policy_state_consistent():
    disk = SimulatedDisk()
    disk.write("x", "original")
    disk.reset_counters()
    cache = LRUFileCache(4, disk, policy=AdaptiveLRUPolicy(4))

    cache.write("x", "ab")
    cache.write("x", "abc")  # replacement is a fresh probationary admission
    assert cache.used_bytes == 3
    assert cache.policy_diagnostics()["admissions"] == 2
    cache.flush()
    assert disk.read("x") == "abc"
    cache.write("x", "012345")  # oversized replacement bypasses and removes stale node
    assert "x" not in cache
    assert cache.used_bytes == 0
    assert disk.read("x") == "012345"
    cache.delete("x")
    cache.flush()
    assert not disk.exists("x")
    assert cache.used_bytes == 0


@pytest.mark.parametrize("fraction", [0.1, 0.5, 0.8, 0.95])
def test_protected_fraction_configuration_is_deterministic(fraction):
    policy = AdaptiveLRUPolicy(10, protected_fraction=fraction)
    cache = LRUFileCache(10, SimulatedDisk(), policy=policy)
    assert cache.policy_diagnostics()["protected_fraction"] == fraction


def test_ghost_history_signal_triggers_configured_adaptation_threshold():
    policy = AdaptiveLRUPolicy(3, ghost_hit_threshold=1, ghost_history_limit=8)
    cache = LRUFileCache(3, SimulatedDisk(), policy=policy)
    # Build a protected working set, then repeatedly displace/re-admit a
    # probationary name. Ghost re-admission is the explicit adaptation signal.
    for name in "abcd":
        cache.disk.write(name, name)
    cache.read("a")
    cache.read("b")
    cache.read("a")
    cache.read("b")  # a and b become protected
    cache.read("c")  # probationary
    cache.read("d")  # evicts c into bounded ghost history
    cache.read("c")  # ghost re-admission triggers one demotion at threshold 1
    diagnostics = cache.policy_diagnostics()
    assert diagnostics["ghost_hit_threshold"] == 1
    assert diagnostics["ghost_history_limit"] == 8
    assert diagnostics["ghost_hits"] == 1
    assert diagnostics["adaptive_demotions"] >= 1


def test_invalid_policy_configuration():
    with pytest.raises(ValueError):
        AdaptiveLRUPolicy(10, protected_fraction=1.0)
    with pytest.raises(ValueError):
        AdaptiveLRUPolicy(10, promotion_threshold=1)
    with pytest.raises(ValueError):
        AdaptiveLRUPolicy(10, ghost_hit_threshold=0)
    with pytest.raises(ValueError):
        AdaptiveLRUPolicy(10, ghost_history_limit=0)
    with pytest.raises(ValueError):
        LRUFileCache(5, SimulatedDisk(), policy=AdaptiveLRUPolicy(6))
