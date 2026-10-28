"""Step-wise and complete simulation orchestration."""

from __future__ import annotations

from time import perf_counter
from typing import Iterable, Optional, Sequence

from .cache import LRUFileCache, _content_size_bytes
from .disk import SimulatedDisk
from .metrics import SimulationMetrics
from .policies import AdaptiveLRUPolicy, CachePolicy, StandardLRUPolicy
from .schemas import CacheRequest, RequestOutcome, SimulationResult


class SimulationEngine:
    """Execute a request trace against a cache without exposing future requests.

    ``step`` executes exactly one request. The engine holds the trace iterator,
    but the policy receives only ordinary cache callbacks for the current
    operation; no workload labels, seed, or future requests reach the policy.
    Storage latency and cost are configurable simulation parameters and are
    reported separately from measured Python wall-clock execution time.
    """

    def __init__(
        self,
        capacity_bytes: int,
        requests: Iterable[CacheRequest],
        *,
        policy: str | CachePolicy = "lru",
        initial_files: Optional[dict[str, str]] = None,
        seed: Optional[int] = None,
        read_latency_seconds: float = 0.005,
        write_latency_seconds: float = 0.010,
        read_cost: float = 1.0,
        write_cost: float = 2.0,
    ) -> None:
        for label, value in (("read_latency_seconds", read_latency_seconds), ("write_latency_seconds", write_latency_seconds), ("read_cost", read_cost), ("write_cost", write_cost)):
            if value < 0:
                raise ValueError(f"{label} must be non-negative")
        self.capacity_bytes = capacity_bytes
        self.requests = tuple(requests)
        self.seed = seed
        self.read_latency_seconds = float(read_latency_seconds)
        self.write_latency_seconds = float(write_latency_seconds)
        self.read_cost = float(read_cost)
        self.write_cost = float(write_cost)
        self.disk = SimulatedDisk()
        for name, content in (initial_files or {}).items():
            self.disk.write(name, content)
        self.disk.reset_counters()
        if isinstance(policy, str):
            if policy == "lru":
                self.policy: CachePolicy = StandardLRUPolicy()
            elif policy in ("adaptive", "adaptive_lru"):
                self.policy = AdaptiveLRUPolicy(capacity_bytes)
            else:
                raise ValueError(f"unknown policy: {policy!r}")
        else:
            self.policy = policy
        self.cache_events: list[str] = []
        self.cache = LRUFileCache(capacity_bytes, self.disk, on_event=self.cache_events.append, policy=self.policy)
        self.metrics = SimulationMetrics(capacity_bytes=capacity_bytes)
        self.outcomes: list[RequestOutcome] = []
        self._next_index = 0

    @property
    def done(self) -> bool:
        return self._next_index >= len(self.requests)

    def step(self) -> Optional[RequestOutcome]:
        """Execute the next request, or return ``None`` when complete."""
        if self.done:
            return None
        request = self.requests[self._next_index]
        index = self._next_index
        self._next_index += 1
        keys_before = set(self.cache.keys())
        used_before = self.cache.used_bytes
        hits_before, misses_before = self.cache.stats.hits, self.cache.stats.misses
        disk_reads_before, disk_writes_before = self.disk.reads, self.disk.writes
        diag_before = self.cache.policy_diagnostics()
        event_start = len(self.cache_events)
        result: Optional[str] = None
        error: Optional[str] = None
        hit: Optional[bool] = None
        miss: Optional[bool] = None
        started = perf_counter()
        try:
            if request.operation == "read":
                hit = request.name in self.cache
                miss = not hit
                result = self.cache.read(request.name or "")
            elif request.operation == "write":
                hit = request.name in self.cache
                miss = not hit
                self.cache.write(request.name or "", request.content or "")
            elif request.operation == "delete":
                self.cache.delete(request.name or "")
            elif request.operation == "flush":
                self.cache.flush()
        except Exception as exc:  # capture a failed operation as an outcome, not a broken run
            error = f"{type(exc).__name__}: {exc}"
        elapsed = perf_counter() - started
        events = self.cache_events[event_start:]
        evicted = tuple(
            event.split("] ", 1)[1].split(" (", 1)[0]
            for event in events if event.startswith("[EVICT] ")
        )
        write_backs = tuple(
            event.split("] ", 1)[1].split(" ", 1)[0]
            for event in events if event.startswith("[FLUSH] ")
        )
        write_backs += tuple(
            event.split("] ", 1)[1].split(" ", 1)[0]
            for event in events if event.startswith("[EVICT] ") and "dirty -> written back" in event
        )
        keys_after = set(self.cache.keys())
        after_diag = self.cache.policy_diagnostics()
        admitted = False
        bypassed = any(event.startswith("[BYPASS]") for event in events)
        if request.operation == "read" and miss and request.name in keys_after:
            admitted = True
        elif request.operation == "write" and not bypassed and request.name in keys_after:
            admitted = True
        promotions = int(after_diag.get("promotions", 0)) - int(diag_before.get("promotions", 0))
        scan_decisions = int(after_diag.get("scan_related_decisions", 0)) - int(diag_before.get("scan_related_decisions", 0))
        disk_reads_delta = self.disk.reads - disk_reads_before
        disk_writes_delta = self.disk.writes - disk_writes_before
        simulated_storage = disk_reads_delta * self.read_latency_seconds + disk_writes_delta * self.write_latency_seconds
        simulated_cost = disk_reads_delta * self.read_cost + disk_writes_delta * self.write_cost
        # Enforce and check the engine's hard invariant after every request.
        if self.cache.used_bytes < 0 or self.cache.used_bytes > self.capacity_bytes:
            raise AssertionError("cache byte-capacity invariant violated")
        calculated = sum(node.size for node in self.cache.entries())
        if calculated != self.cache.used_bytes:
            raise AssertionError("cache byte accounting invariant violated")
        outcome = RequestOutcome(
            index=index, request=request, hit=hit, miss=miss, admitted=admitted,
            bypassed=bypassed, promotions=max(0, promotions),
            scan_related_decisions=max(0, scan_decisions), evicted=evicted,
            write_backs=write_backs, result=result, error=error,
            cache_used_bytes=self.cache.used_bytes, capacity_bytes=self.capacity_bytes,
            disk_reads_delta=disk_reads_delta, disk_writes_delta=disk_writes_delta,
            elapsed_seconds=elapsed, simulated_storage_seconds=simulated_storage,
            simulated_cost=simulated_cost, policy_diagnostics=after_diag,
        )
        self.outcomes.append(outcome)
        self.metrics.update(outcome)
        return outcome

    def run(self) -> SimulationResult:
        """Execute all remaining requests and return a complete result snapshot."""
        while not self.done:
            self.step()
        return self.result()

    def result(self) -> SimulationResult:
        """Return current results; useful after any number of step calls."""
        return SimulationResult(
            capacity_bytes=self.capacity_bytes,
            policy_name=str(self.cache.policy_diagnostics().get("policy", self.policy.name)),
            seed=self.seed, outcomes=tuple(self.outcomes), metrics=self.metrics.as_dict(),
            final_cache_keys_mru_to_lru=tuple(self.cache.keys()),
            final_disk_files=tuple(self.disk.list_files()),
            policy_diagnostics=self.cache.policy_diagnostics(),
        )


def compare_policies(
    capacity_bytes: int, requests: Sequence[CacheRequest], *,
    initial_files: Optional[dict[str, str]] = None, seed: Optional[int] = None,
    **costs: float,
) -> dict[str, SimulationResult]:
    """Run both built-in policies against the exact same immutable trace."""
    trace = tuple(requests)
    initial = dict(initial_files or {})
    return {
        name: SimulationEngine(capacity_bytes, trace, policy=name,
                               initial_files=initial, seed=seed, **costs).run()
        for name in ("lru", "adaptive")
    }
