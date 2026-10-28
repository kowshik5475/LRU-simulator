"""Compare standard LRU and adaptive scan-resistant admission on identical traces.

Run from the repository root with:
    PYTHONPATH=src python benchmarks/compare_policies.py

The script reports observed metrics only; it does not assume either policy wins.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from filecache_sim import AdaptiveLRUPolicy, LRUFileCache, SimulatedDisk


Workload = Tuple[List[str], int, Dict[str, int]]


def workloads() -> Dict[str, Workload]:
    names = [f"f{i:02}" for i in range(40)]
    unit_sizes = {name: 1 for name in names}
    hot = ["f00", "f01", "f02"]
    changing_hot: List[str] = []
    for group in (["f00", "f01", "f02"], ["f10", "f11", "f12"], ["f20", "f21", "f22"]):
        changing_hot.extend(group * 12)
    rng = random.Random(20261028)
    mixed_sizes = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 2, "h": 3}
    return {
        "hot working set": (hot * 40, 8, unit_sizes),
        "sequential scan": (names, 8, unit_sizes),
        "hot + interrupted scan": (hot * 12 + names[3:35] + hot * 12, 8, unit_sizes),
        "uniform random": ([rng.choice(names) for _ in range(400)], 8, unit_sizes),
        "changing hot sets": (changing_hot, 8, unit_sizes),
        "mixed file sizes": (["a", "b", "a", "c", "b", "d", "a", "e", "f", "g", "h", "a", "b"] * 5, 10, mixed_sizes),
    }


def simulate(policy_name: str, trace: List[str], capacity: int, sizes: Dict[str, int]) -> dict:
    disk = SimulatedDisk()
    for name, size in sizes.items():
        disk.write(name, "x" * size)
    disk.reset_counters()
    policy = AdaptiveLRUPolicy(capacity) if policy_name == "adaptive" else None
    cache = LRUFileCache(capacity, disk, policy=policy)
    for name in trace:
        cache.read(name)
    return {
        "hits": cache.stats.hits,
        "misses": cache.stats.misses,
        "hit_ratio": cache.stats.hit_ratio,
        "evictions": cache.stats.evictions,
        "used_bytes": cache.used_bytes,
        "policy_diagnostics": cache.policy_diagnostics(),
    }


def main() -> None:
    print("workload | capacity | policy | hits | misses | hit ratio | evictions | used bytes")
    for name, (trace, capacity, sizes) in workloads().items():
        for policy_name in ("lru", "adaptive"):
            result = simulate(policy_name, trace, capacity, sizes)
            print(
                f"{name} | {capacity} | {policy_name} | {result['hits']} | "
                f"{result['misses']} | {result['hit_ratio']:.1%} | "
                f"{result['evictions']} | {result['used_bytes']}"
            )
            if policy_name == "adaptive":
                diagnostics = result["policy_diagnostics"]
                print(
                    f"  diagnostics: promotions={diagnostics['promotions']}, "
                    f"scan_related_decisions={diagnostics['scan_related_decisions']}, "
                    f"admissions={diagnostics['admissions']}, "
                    f"ghost_hits={diagnostics['ghost_hits']}, "
                    f"adaptive_demotions={diagnostics['adaptive_demotions']}"
                )


if __name__ == "__main__":
    main()
