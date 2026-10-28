# Technical Report: Custom LRU-Based Adaptive File Cache Simulator

## Abstract

This project is an educational simulation of a byte-bounded file cache. It provides a standard Least Recently Used (LRU) baseline and a configurable scan-resistant policy, plus seeded workload generation, metrics, a CLI, a FastAPI interface, and a React dashboard. The purpose is to make cache admission, eviction, write-back, and workload sensitivity observable and reproducible—not to claim a new replacement algorithm or to measure real storage devices.

## Problem and scope

A cache has finite capacity. When a new object does not fit, resident entries must be evicted. LRU is a useful baseline because it evicts the least recently accessed resident item, but a one-time scan can push repeatedly used entries out of the cache. The project explores a segmented policy that gives entries a probationary period before they receive protected status.

The storage abstraction is deliberately simulated: file content lives in Python memory in `SimulatedDisk`. Logical disk reads/writes and modeled latency/cost are counters and arithmetic, not physical disk operations.

## Standard LRU

The cache engine maintains filename-to-entry lookup and a doubly linked recency list. Access moves an entry to the most-recently-used end. On a miss that needs space, standard LRU selects the least-recently-used entry.

Assuming expected constant-time dictionary operations and list-pointer updates:
- Lookup/access recency update: **O(1)** expected.
- Victim selection: **O(1)**.
- Eviction of a selected entry: **O(1)** for recency unlinking, excluding any write-back work.
- Space: **O(n)** for `n` resident entries, plus entry content and metadata.

The byte-capacity constraint means a single insertion may evict multiple entries; its total cost is proportional to the number of evictions required, plus content and write-back costs.

## Custom scan-resistant policy

`AdaptiveLRUPolicy` maintains two ordered segments:
- **Probationary**: new admissions start here. Admission counts as the first observed use.
- **Protected**: an item is promoted after its observed-use count reaches `promotion_threshold` (default 2).

Each segment maintains LRU order. Eviction chooses the least-recently-used probationary entry first; it falls back to protected LRU only when probationary is empty. A soft protected-byte target (`protected_fraction`, default 0.8) demotes protected LRU entries when the segment grows beyond its target, except that a single item larger than the target may remain protected.

A bounded ghost history stores filenames of evicted probationary entries—not content. When a ghosted filename is admitted again, it contributes a ghost hit. Every `ghost_hit_threshold` ghost hits (default 2), the policy attempts to demote one protected LRU entry, allowing a previously evicted working-set item to compete for protected space. Ghost history is bounded by `ghost_history_limit` (default 256). No future requests or workload labels are consulted.

### Algorithm sketch

```text
on admission(name):
    if name is in bounded ghost history:
        count ghost hit
        if ghost-hit threshold reached:
            demote one protected LRU entry
    add name to probationary with use_count = 1

on access(name):
    if protected:
        move to protected MRU
    else if probationary:
        increment use_count; move to probationary MRU
        if use_count >= promotion_threshold:
            promote to protected MRU
            demote protected LRU entries while over soft byte target

choose victim:
    if probationary is not empty: probationary LRU
    else: protected LRU
```

## Complexity and trade-offs

The standard cache's lookup/recency operations are expected O(1). The adaptive policy uses ordered dictionaries for segment recency and a bounded ghost history. Common accesses and segment moves are expected O(1). A protected-target rebalance may demote multiple entries in one promotion, so the worst-case work for that operation is O(n); ghost-history maintenance can evict the oldest ghost entry in O(1). Resident state is O(n), and ghost metadata is O(g), where `g` is capped by the configured history limit. Content size dominates memory use; metadata adds overhead not reflected in the byte-capacity counter.

**Benefits:** a probationary admission phase can prevent single-use scan entries from immediately receiving protected status; policy diagnostics make promotions/demotions and segment occupancy observable; parameters are deterministic and configurable.

**Costs/risks:** the extra bookkeeping adds runtime and metadata; a promotion threshold can delay protection for genuinely useful items; ghost history may not capture every workload shift; probationary-first eviction is not optimal for every trace; and a poor parameter choice can perform worse than standard LRU. The “scan-related decision” counter is a policy diagnostic, not proof that an eviction was caused by a real-world scan.

This policy borrows established concepts from segmented LRU and 2Q-style designs. Its particular parameterization and combination are engineering choices in this project. No scientific novelty claim is made.

## Capacity and write-back semantics

- Capacity is a positive integer in bytes.
- Content size is `len(content.encode("utf-8"))`.
- Empty content is allowed and occupies zero accounted bytes.
- An item larger than capacity bypasses cache admission. Oversized writes go to simulated disk directly.
- Cached writes mark entries dirty; dirty content is persisted to the simulated disk on eviction or `flush()`.
- The engine checks the hard byte-capacity invariant after requests.
- This is not a full filesystem: it does not implement directories, permissions, crash recovery, durability guarantees, concurrency semantics of a real filesystem, or host file I/O.

## Experimental design

The benchmark suite compares both policies against identical generated request traces and initial simulated-disk contents for each seed/scenario/capacity. Workloads are generated deterministically from seed values. The trace fingerprint in API comparisons supports checking that both policies saw the same operations. The full recorded run uses five seeds and 500 requests per workload/seed. See [BENCHMARKS.md](BENCHMARKS.md) for actual results and caveats.

## Conclusion

The project demonstrates a complete path from cache policy code to repeatable workload experiments, API contracts, and a visualization layer. Results are workload-dependent: the checked-in experiment shows a small adaptive advantage on the skewed-popularity workload, near parity on mixed I/O, and no advantage on some other traces. These observations are limited to this simulator and the selected configuration; they do not establish general superiority or real storage performance.


## Metric semantics

The read hit ratio is read hits divided by read hits plus read misses. Write hits and write misses are reported separately, so write activity does not inflate or depress the read hit ratio. The overall request count also includes writes, deletes, and flushes.
