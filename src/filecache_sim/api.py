"""FastAPI application for the Python cache simulator.

All cache operations delegate to :mod:`filecache_sim.simulation`; API handlers
only validate, coordinate, and serialize simulator state. The backing store is
always the in-memory SimulatedDisk and never the host filesystem.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from . import __version__
from .schemas import CacheRequest
from .simulation import SimulationEngine, compare_policies
from .workloads import generate_workload

MAX_CAPACITY_BYTES = 10_000_000
MAX_REQUESTS = 20_000
MAX_FILES = 5_000
MAX_SESSIONS = 128
MAX_CONCURRENT_BENCHMARKS = 2
DEVELOPMENT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://LRU-simulator.onrender.com",
]
WORKLOADS = (
    "sequential_scan", "hot_set", "uniform_random", "skewed_popularity",
    "changing_hot_set", "mixed_sizes_io",
)
POLICIES = ("lru", "adaptive")


class SimulationConfig(BaseModel):
    """Validated simulation setup; workload labels stay outside policy inputs."""

    model_config = ConfigDict(extra="forbid")

    capacity_bytes: int = Field(gt=0, le=MAX_CAPACITY_BYTES)
    policy: Literal["lru", "adaptive"] = "lru"
    workload: Literal[
        "sequential_scan", "hot_set", "uniform_random", "skewed_popularity",
        "changing_hot_set", "mixed_sizes_io",
    ] = "hot_set"
    request_count: int = Field(default=500, ge=0, le=MAX_REQUESTS)
    seed: int = Field(default=2026, ge=0, le=2**32 - 1)
    file_count: int = Field(default=100, ge=1, le=MAX_FILES)
    hot_set_size: int = Field(default=5, ge=1, le=MAX_FILES)
    read_latency_seconds: float = Field(default=0.005, ge=0, le=60)
    write_latency_seconds: float = Field(default=0.010, ge=0, le=60)
    read_cost: float = Field(default=1.0, ge=0, le=1_000_000)
    write_cost: float = Field(default=2.0, ge=0, le=1_000_000)


class SimulationCreatedResponse(BaseModel):
    simulation_id: str
    status: Literal["ready"]
    config: SimulationConfig
    request_count: int
    created_at: datetime


class CacheEntryResponse(BaseModel):
    name: str
    content: str
    size_bytes: int
    dirty: bool
    recency_rank: int


class SimulationStateResponse(BaseModel):
    simulation_id: str
    status: Literal["ready", "running", "completed"]
    config: SimulationConfig
    next_request_index: int
    total_requests: int
    done: bool
    cache_entries_mru_to_lru: list[CacheEntryResponse]
    recency_order_mru_to_lru: list[str]
    used_bytes: int
    capacity_bytes: int
    capacity_utilization: float
    metrics: dict[str, int | float]
    policy_diagnostics: dict[str, int | float | str]
    disk_files: list[str]
    disk_reads: int
    disk_writes: int
    last_outcome: dict[str, Any] | None = None


class StepResponse(BaseModel):
    simulation_id: str
    status: Literal["ready", "completed"]
    done: bool
    outcome: dict[str, Any] | None
    state: SimulationStateResponse


class BenchmarkCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity_bytes: int = Field(gt=0, le=MAX_CAPACITY_BYTES)
    workload: Literal[
        "sequential_scan", "hot_set", "uniform_random", "skewed_popularity",
        "changing_hot_set", "mixed_sizes_io",
    ] = "hot_set"
    request_count: int = Field(default=500, ge=0, le=MAX_REQUESTS)
    seed: int = Field(default=2026, ge=0, le=2**32 - 1)
    file_count: int = Field(default=100, ge=1, le=MAX_FILES)
    hot_set_size: int = Field(default=5, ge=1, le=MAX_FILES)
    read_latency_seconds: float = Field(default=0.005, ge=0, le=60)
    write_latency_seconds: float = Field(default=0.010, ge=0, le=60)
    read_cost: float = Field(default=1.0, ge=0, le=1_000_000)
    write_cost: float = Field(default=2.0, ge=0, le=1_000_000)


class BenchmarkPolicyResult(BaseModel):
    policy: Literal["lru", "adaptive"]
    metrics: dict[str, int | float]
    policy_diagnostics: dict[str, int | float | str]
    final_cache_keys_mru_to_lru: list[str]
    outcomes_recorded: int


class BenchmarkCompareResponse(BaseModel):
    seed: int
    workload: str
    request_count: int
    capacity_bytes: int
    trace_fingerprint: str
    same_trace_for_both_policies: bool
    policies: dict[str, BenchmarkPolicyResult]


class DeleteSimulationResponse(BaseModel):
    simulation_id: str
    deleted: Literal[True] = True


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    engine: str
    storage: str


class _SimulationRecord:
    def __init__(self, simulation_id: str, config: SimulationConfig, engine: SimulationEngine) -> None:
        self.simulation_id = simulation_id
        self.config = config
        self.engine = engine
        self.created_at = datetime.now(timezone.utc)
        self.lock = threading.RLock()
        self.last_outcome: dict[str, Any] | None = None
        self.status: Literal["ready", "running", "completed"] = "ready"


app = FastAPI(
    title="Custom LRU Cache Simulator API",
    version=__version__,
    description="HTTP interface to the Python cache simulation engine. The disk is simulated in memory.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEVELOPMENT_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

_sessions: dict[str, _SimulationRecord] = {}
_sessions_lock = threading.RLock()
_benchmark_slots = threading.BoundedSemaphore(MAX_CONCURRENT_BENCHMARKS)


def _get_session(simulation_id: str) -> _SimulationRecord:
    with _sessions_lock:
        record = _sessions.get(simulation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return record


def _outcome_dict(outcome: Any) -> dict[str, Any]:
    data = asdict(outcome)
    request = data.get("request")
    if request is not None:
        data["request"] = asdict(outcome.request)
    if isinstance(data.get("evicted"), tuple):
        data["evicted"] = list(data["evicted"])
    if isinstance(data.get("write_backs"), tuple):
        data["write_backs"] = list(data["write_backs"])
    return data


def _state(record: _SimulationRecord) -> SimulationStateResponse:
    engine = record.engine
    with record.lock:
        entries = [
            CacheEntryResponse(
                name=node.name,
                content=node.content,
                size_bytes=node.size,
                dirty=node.dirty,
                recency_rank=index,
            )
            for index, node in enumerate(engine.cache.entries())
        ]
        used = engine.cache.used_bytes
        return SimulationStateResponse(
            simulation_id=record.simulation_id,
            status="completed" if engine.done else record.status,
            config=record.config,
            next_request_index=len(engine.outcomes),
            total_requests=len(engine.requests),
            done=engine.done,
            cache_entries_mru_to_lru=entries,
            recency_order_mru_to_lru=[entry.name for entry in entries],
            used_bytes=used,
            capacity_bytes=engine.capacity_bytes,
            capacity_utilization=used / engine.capacity_bytes,
            metrics=engine.metrics.as_dict(),
            policy_diagnostics=engine.cache.policy_diagnostics(),
            disk_files=engine.disk.list_files(),
            disk_reads=engine.disk.reads,
            disk_writes=engine.disk.writes,
            last_outcome=record.last_outcome,
        )


def _fingerprint(requests: tuple[CacheRequest, ...]) -> str:
    payload = [
        {"operation": request.operation, "name": request.name, "content": request.content}
        for request in requests
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_engine(config: SimulationConfig) -> SimulationEngine:
    workload = generate_workload(
        config.workload,
        request_count=config.request_count,
        seed=config.seed,
        file_count=config.file_count,
        hot_set_size=config.hot_set_size,
    )
    return SimulationEngine(
        config.capacity_bytes,
        workload.requests,
        policy=config.policy,
        initial_files=workload.initial_files,
        seed=config.seed,
        read_latency_seconds=config.read_latency_seconds,
        write_latency_seconds=config.write_latency_seconds,
        read_cost=config.read_cost,
        write_cost=config.write_cost,
    )


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        engine="filecache_sim.SimulationEngine",
        storage="in-memory SimulatedDisk; host filesystem access disabled",
    )


@app.post("/api/simulations", response_model=SimulationCreatedResponse, status_code=201, tags=["simulations"])
def create_simulation(config: SimulationConfig) -> SimulationCreatedResponse:
    if config.hot_set_size > config.file_count:
        raise HTTPException(status_code=422, detail="hot_set_size cannot exceed file_count")
    with _sessions_lock:
        if len(_sessions) >= MAX_SESSIONS:
            raise HTTPException(status_code=503, detail="Simulation capacity reached; try again later")
        simulation_id = str(uuid.uuid4())
        try:
            engine = _build_engine(config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _sessions[simulation_id] = _SimulationRecord(simulation_id, config, engine)
    return SimulationCreatedResponse(
        simulation_id=simulation_id, status="ready", config=config,
        request_count=config.request_count, created_at=_sessions[simulation_id].created_at,
    )


@app.post("/api/simulations/{simulation_id}/run", response_model=SimulationStateResponse, tags=["simulations"])
def run_simulation(simulation_id: str) -> SimulationStateResponse:
    record = _get_session(simulation_id)
    with record.lock:
        if record.engine.done:
            record.status = "completed"
            return _state(record)
        record.status = "running"
        try:
            record.engine.run()
        finally:
            record.status = "completed" if record.engine.done else "ready"
        return _state(record)


@app.post("/api/simulations/{simulation_id}/step", response_model=StepResponse, tags=["simulations"])
def step_simulation(simulation_id: str) -> StepResponse:
    record = _get_session(simulation_id)
    with record.lock:
        outcome = record.engine.step()
        record.last_outcome = _outcome_dict(outcome) if outcome is not None else None
        record.status = "completed" if record.engine.done else "ready"
        state = _state(record)
        return StepResponse(
            simulation_id=simulation_id,
            status=record.status,
            done=record.engine.done,
            outcome=record.last_outcome,
            state=state,
        )


@app.get("/api/simulations/{simulation_id}/state", response_model=SimulationStateResponse, tags=["simulations"])
def simulation_state(simulation_id: str) -> SimulationStateResponse:
    return _state(_get_session(simulation_id))


@app.delete(
    "/api/simulations/{simulation_id}",
    response_model=DeleteSimulationResponse,
    tags=["simulations"],
)
def delete_simulation(simulation_id: str) -> DeleteSimulationResponse:
    """Release an in-memory simulation session and its recorded request trace."""
    record = _get_session(simulation_id)
    # Lock the record before removing it so an in-flight step/run finishes first.
    with record.lock:
        with _sessions_lock:
            if _sessions.get(simulation_id) is not record:
                raise HTTPException(status_code=404, detail="Simulation not found")
            del _sessions[simulation_id]
    return DeleteSimulationResponse(simulation_id=simulation_id, deleted=True)


def _result_payload(record: _SimulationRecord) -> dict[str, Any]:
    result = record.engine.result()
    return {
        "simulation_id": record.simulation_id,
        "capacity_bytes": result.capacity_bytes,
        "policy": result.policy_name,
        "seed": result.seed,
        "metrics": result.metrics,
        "final_cache_keys_mru_to_lru": list(result.final_cache_keys_mru_to_lru),
        "final_disk_files": list(result.final_disk_files),
        "policy_diagnostics": result.policy_diagnostics,
        "outcomes": [_outcome_dict(outcome) for outcome in result.outcomes],
    }


@app.get("/api/simulations/{simulation_id}/export", tags=["simulations"])
def export_simulation(
    simulation_id: str,
    format: Literal["json", "csv"] = Query(default="json"),
) -> Response:
    record = _get_session(simulation_id)
    with record.lock:
        payload = _result_payload(record)
    if format == "json":
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="simulation-{simulation_id}.json"'},
        )
    output = io.StringIO(newline="")
    fields = [
        "index", "operation", "name", "content", "hit", "miss", "admitted",
        "bypassed", "promotions", "scan_related_decisions", "evicted",
        "write_backs", "cache_used_bytes", "capacity_bytes", "disk_reads_delta",
        "disk_writes_delta", "elapsed_seconds", "simulated_storage_seconds",
        "simulated_cost", "error",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for outcome in payload["outcomes"]:
        request = outcome["request"]
        row = {**outcome, "operation": request["operation"], "name": request["name"], "content": request["content"]}
        row["evicted"] = json.dumps(row.get("evicted", []), ensure_ascii=False)
        row["write_backs"] = json.dumps(row.get("write_backs", []), ensure_ascii=False)
        writer.writerow(row)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="simulation-{simulation_id}.csv"'},
    )


def _compare_sync(request: BenchmarkCompareRequest) -> BenchmarkCompareResponse:
    workload = generate_workload(
        request.workload,
        request_count=request.request_count,
        seed=request.seed,
        file_count=request.file_count,
        hot_set_size=request.hot_set_size,
    )
    results = compare_policies(
        request.capacity_bytes,
        workload.requests,
        initial_files=workload.initial_files,
        seed=request.seed,
        read_latency_seconds=request.read_latency_seconds,
        write_latency_seconds=request.write_latency_seconds,
        read_cost=request.read_cost,
        write_cost=request.write_cost,
    )
    policies: dict[str, BenchmarkPolicyResult] = {}
    for name in POLICIES:
        result = results[name]
        policies[name] = BenchmarkPolicyResult(
            policy=name,
            metrics=result.metrics,
            policy_diagnostics=result.policy_diagnostics,
            final_cache_keys_mru_to_lru=list(result.final_cache_keys_mru_to_lru),
            outcomes_recorded=len(result.outcomes),
        )
    return BenchmarkCompareResponse(
        seed=request.seed,
        workload=request.workload,
        request_count=len(workload.requests),
        capacity_bytes=request.capacity_bytes,
        trace_fingerprint=_fingerprint(workload.requests),
        same_trace_for_both_policies=True,
        policies=policies,
    )


@app.post("/api/benchmarks/compare", response_model=BenchmarkCompareResponse, tags=["benchmarks"])
async def benchmark_compare(request: BenchmarkCompareRequest) -> BenchmarkCompareResponse:
    """Run a bounded paired benchmark off the event loop; reject overload promptly."""
    if request.hot_set_size > request.file_count:
        raise HTTPException(status_code=422, detail="hot_set_size cannot exceed file_count")
    if not _benchmark_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Benchmark capacity is busy; retry shortly")
    try:
        # Starlette's threadpool keeps CPU work off the async event loop; the
        # semaphore bounds concurrent benchmark jobs.
        return await run_in_threadpool(_compare_sync, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        _benchmark_slots.release()
