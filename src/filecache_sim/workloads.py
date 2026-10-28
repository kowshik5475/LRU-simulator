"""Deterministic synthetic workload generation for cache experiments."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Iterable, Literal, Optional, Tuple

from .schemas import CacheRequest

WorkloadKind = Literal[
    "sequential_scan", "hot_set", "uniform_random", "skewed_popularity",
    "changing_hot_set", "mixed_sizes_io",
]


@dataclass(frozen=True)
class Workload:
    """Generated workload; labels stay outside individual requests and policies."""

    name: str
    requests: Tuple[CacheRequest, ...]
    initial_files: Dict[str, str]
    seed: int


def generate_workload(
    kind: WorkloadKind | str,
    *,
    request_count: int = 500,
    seed: int = 0,
    file_count: int = 100,
    hot_set_size: int = 5,
) -> Workload:
    """Generate repeatable requests and initial simulated-disk contents.

    All random choices use a private ``random.Random(seed)``. File contents are
    ASCII so their encoded byte size equals the requested length. The returned
    request records do not contain the workload name or any future trace data.
    """
    if isinstance(request_count, bool) or not isinstance(request_count, int) or request_count < 0:
        raise ValueError("request_count must be a non-negative integer")
    if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count < 1:
        raise ValueError("file_count must be a positive integer")
    if isinstance(hot_set_size, bool) or not isinstance(hot_set_size, int) or hot_set_size < 1:
        raise ValueError("hot_set_size must be a positive integer")
    rng = random.Random(seed)
    names = [f"file_{i:04d}.dat" for i in range(file_count)]
    if kind not in {"sequential_scan", "hot_set", "uniform_random", "skewed_popularity", "changing_hot_set", "mixed_sizes_io"}:
        raise ValueError(f"unknown workload kind: {kind!r}")

    sizes: Dict[str, int] = {}
    for i, name in enumerate(names):
        if kind == "mixed_sizes_io":
            sizes[name] = (1, 2, 4, 8, 16, 32, 64)[i % 7]
        else:
            sizes[name] = 16
    initial = {name: "x" * size for name, size in sizes.items()}
    requests: list[CacheRequest] = []
    hot_n = min(hot_set_size, file_count)
    hot = names[:hot_n]

    for i in range(request_count):
        if kind == "sequential_scan":
            name = names[i % file_count]
        elif kind == "hot_set":
            name = hot[i % hot_n] if i % 4 else rng.choice(hot)
        elif kind == "uniform_random":
            name = rng.choice(names)
        elif kind == "skewed_popularity":
            # Zipf-like categorical weighting without external dependencies.
            name = rng.choices(names, weights=[1.0 / (rank + 1) for rank in range(file_count)], k=1)[0]
        elif kind == "changing_hot_set":
            group_size = hot_n
            group = (i // max(1, request_count // 4)) % max(1, (file_count + group_size - 1) // group_size)
            group_names = names[group * group_size:(group + 1) * group_size] or names[-group_size:]
            name = rng.choice(group_names)
        else:
            name = rng.choice(names)

        if kind == "mixed_sizes_io" and rng.random() < 0.30:
            new_size = rng.choice((0, 1, 3, 8, 24, 48, 96))
            requests.append(CacheRequest("write", name, "w" * new_size))
        elif kind == "mixed_sizes_io" and rng.random() < 0.04:
            requests.append(CacheRequest("delete", name))
        else:
            requests.append(CacheRequest("read", name))

    # Ensure a generated delete does not accidentally affect the initial state:
    # operations are still valid if the target is absent, which is intentional.
    return Workload(str(kind), tuple(requests), initial, seed)


def generate_workloads(
    kinds: Iterable[WorkloadKind | str] = (
        "sequential_scan", "hot_set", "uniform_random", "skewed_popularity",
        "changing_hot_set", "mixed_sizes_io",
    ),
    *, request_count: int = 500, seed: int = 0, file_count: int = 100,
    hot_set_size: int = 5,
) -> Tuple[Workload, ...]:
    """Generate several workloads with reproducible, distinct derived seeds."""
    return tuple(
        generate_workload(kind, request_count=request_count,
                          seed=seed + index, file_count=file_count,
                          hot_set_size=hot_set_size)
        for index, kind in enumerate(kinds)
    )
