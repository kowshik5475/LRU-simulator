"""Aggregate metrics for cache simulation runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schemas import RequestOutcome


@dataclass
class SimulationMetrics:
    """Metrics are observations of the run, not inputs to the policy."""

    requests: int = 0
    # ``hits`` and ``misses`` count read requests, matching CacheStats.hit_ratio.
    # Write-allocate outcomes are tracked separately so write activity cannot
    # silently inflate or depress the read hit ratio reported in benchmarks.
    hits: int = 0
    misses: int = 0
    write_hits: int = 0
    write_misses: int = 0
    admissions: int = 0
    promotions: int = 0
    scan_related_decisions: int = 0
    bypasses: int = 0
    evictions: int = 0
    write_backs: int = 0
    disk_reads: int = 0
    disk_writes: int = 0
    bytes_occupied: int = 0
    capacity_bytes: int = 0
    actual_execution_seconds: float = 0.0
    simulated_storage_seconds: float = 0.0
    simulated_cost: float = 0.0

    @property
    def hit_ratio(self) -> float:
        return self.hits / (self.hits + self.misses) if self.hits + self.misses else 0.0

    @property
    def capacity_utilization(self) -> float:
        return self.bytes_occupied / self.capacity_bytes if self.capacity_bytes else 0.0

    def update(self, outcome: RequestOutcome) -> None:
        self.requests += 1
        if outcome.request.operation == "read":
            if outcome.hit is True:
                self.hits += 1
            if outcome.miss is True:
                self.misses += 1
        elif outcome.request.operation == "write":
            if outcome.hit is True:
                self.write_hits += 1
            if outcome.miss is True:
                self.write_misses += 1
        self.admissions += int(outcome.admitted)
        self.promotions += outcome.promotions
        self.scan_related_decisions += outcome.scan_related_decisions
        self.bypasses += int(outcome.bypassed)
        self.evictions += len(outcome.evicted)
        self.write_backs += len(outcome.write_backs)
        self.disk_reads += outcome.disk_reads_delta
        self.disk_writes += outcome.disk_writes_delta
        self.bytes_occupied = outcome.cache_used_bytes
        self.capacity_bytes = outcome.capacity_bytes
        self.actual_execution_seconds += outcome.elapsed_seconds
        self.simulated_storage_seconds += outcome.simulated_storage_seconds
        self.simulated_cost += outcome.simulated_cost

    def as_dict(self) -> dict[str, int | float]:
        return {
            "requests": self.requests,
            "read_requests": self.hits + self.misses,
            "write_requests": self.write_hits + self.write_misses,
            "hits": self.hits, "misses": self.misses,
            "write_hits": self.write_hits, "write_misses": self.write_misses,
            "hit_ratio": self.hit_ratio, "read_hit_ratio": self.hit_ratio,
            "admissions": self.admissions,
            "promotions": self.promotions,
            "scan_related_decisions": self.scan_related_decisions,
            "bypasses": self.bypasses, "evictions": self.evictions,
            "write_backs": self.write_backs, "bytes_occupied": self.bytes_occupied,
            "capacity_bytes": self.capacity_bytes,
            "capacity_utilization": self.capacity_utilization,
            "disk_reads": self.disk_reads, "disk_writes": self.disk_writes,
            "actual_execution_seconds": self.actual_execution_seconds,
            "simulated_storage_seconds": self.simulated_storage_seconds,
            "simulated_cost": self.simulated_cost,
        }


def aggregate(outcomes: Iterable[RequestOutcome]) -> SimulationMetrics:
    """Build metrics from outcomes in execution order."""
    result = SimulationMetrics()
    for outcome in outcomes:
        result.update(outcome)
    return result
