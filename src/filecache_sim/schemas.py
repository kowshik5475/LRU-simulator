"""Immutable schemas shared by workload generation and simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

Operation = Literal["read", "write", "delete", "flush"]


@dataclass(frozen=True)
class CacheRequest:
    """One logical operation; contains no workload metadata or future requests."""

    operation: Operation
    name: Optional[str] = None
    content: Optional[str] = None

    def __post_init__(self) -> None:
        if self.operation not in ("read", "write", "delete", "flush"):
            raise ValueError(f"unsupported operation: {self.operation!r}")
        if self.operation != "flush" and not self.name:
            raise ValueError("name is required for read, write, and delete")
        if self.operation == "write" and self.content is None:
            raise ValueError("content is required for write requests")
        if self.operation != "write" and self.content is not None:
            raise ValueError("content is only valid for write requests")


@dataclass(frozen=True)
class RequestOutcome:
    """Observed result for one executed request."""

    index: int
    request: CacheRequest
    hit: Optional[bool]
    miss: Optional[bool]
    admitted: bool = False
    bypassed: bool = False
    promotions: int = 0
    scan_related_decisions: int = 0
    evicted: Tuple[str, ...] = ()
    write_backs: Tuple[str, ...] = ()
    result: Optional[str] = None
    error: Optional[str] = None
    cache_used_bytes: int = 0
    capacity_bytes: int = 0
    disk_reads_delta: int = 0
    disk_writes_delta: int = 0
    elapsed_seconds: float = 0.0
    simulated_storage_seconds: float = 0.0
    simulated_cost: float = 0.0
    policy_diagnostics: dict[str, int | float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationResult:
    """Complete run result with immutable request outcomes and aggregate metrics."""

    capacity_bytes: int
    policy_name: str
    seed: Optional[int]
    outcomes: Tuple[RequestOutcome, ...]
    metrics: dict[str, int | float]
    final_cache_keys_mru_to_lru: Tuple[str, ...]
    final_disk_files: Tuple[str, ...]
    policy_diagnostics: dict[str, int | float | str]
