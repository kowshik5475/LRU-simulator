# HTTP API Reference

Base URL for local development: `http://127.0.0.1:8000`. Start with:

```bash
PYTHONPATH=src uvicorn filecache_sim.api:app --host 127.0.0.1 --port 8000 --reload
```

Interactive OpenAPI docs are at `/docs`; schema JSON is at `/openapi.json`. Requests and responses below are representative schema examples; dynamic IDs, timestamps, metrics, and trace hashes vary by request.

## Health

`GET /api/health`

Example response:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "engine": "filecache_sim.SimulationEngine",
  "storage": "in-memory SimulatedDisk; host filesystem access disabled"
}
```

## Create a simulation

`POST /api/simulations` — returns **201 Created**.

```json
{
  "capacity_bytes": 256,
  "policy": "adaptive",
  "workload": "hot_set",
  "request_count": 500,
  "seed": 2026,
  "file_count": 100,
  "hot_set_size": 5,
  "read_latency_seconds": 0.005,
  "write_latency_seconds": 0.01,
  "read_cost": 1.0,
  "write_cost": 2.0
}
```

Representative response shape:

```json
{
  "simulation_id": "dynamic-uuid",
  "status": "ready",
  "config": {
    "capacity_bytes": 256,
    "policy": "adaptive",
    "workload": "hot_set",
    "request_count": 500,
    "seed": 2026,
    "file_count": 100,
    "hot_set_size": 5,
    "read_latency_seconds": 0.005,
    "write_latency_seconds": 0.01,
    "read_cost": 1.0,
    "write_cost": 2.0
  },
  "request_count": 500,
  "created_at": "dynamic ISO-8601 timestamp"
}
```

Allowed policies: `lru`, `adaptive`. Allowed workloads: `sequential_scan`, `hot_set`, `uniform_random`, `skewed_popularity`, `changing_hot_set`, `mixed_sizes_io`. Capacity is 1–10,000,000 bytes; request count 0–20,000; file count 1–5,000; seed 0–2^32-1; latency 0–60 seconds; costs 0–1,000,000. `hot_set_size` must not exceed `file_count`. Extra fields are rejected.

## Step, run, and refresh state

- `POST /api/simulations/{simulation_id}/step` executes one request and returns `outcome`, `done`, and refreshed `state`.
- `POST /api/simulations/{simulation_id}/run` executes all remaining requests and returns the final/current state.
- `GET /api/simulations/{simulation_id}/state` returns current state without executing another request.

State includes `next_request_index`, `total_requests`, `done`, MRU-to-LRU cache entries, `used_bytes`, `capacity_bytes`, `capacity_utilization`, aggregate `metrics`, `policy_diagnostics`, simulated `disk_files`, `disk_reads`, `disk_writes`, and `last_outcome`.

Example `step` response shape:

```json
{
  "simulation_id": "dynamic-uuid",
  "status": "ready",
  "done": false,
  "outcome": {
    "index": 0,
    "request": {"operation": "read", "name": "file-1.txt", "content": null},
    "hit": false,
    "miss": true,
    "admitted": true,
    "bypassed": false,
    "evicted": [],
    "write_backs": [],
    "cache_used_bytes": 12,
    "capacity_bytes": 256
  },
  "state": {
    "simulation_id": "dynamic-uuid",
    "status": "ready",
    "next_request_index": 1,
    "total_requests": 500,
    "done": false,
    "used_bytes": 12,
    "capacity_bytes": 256,
    "capacity_utilization": 0.046875,
    "recency_order_mru_to_lru": ["file-1.txt"],
    "metrics": {},
    "policy_diagnostics": {},
    "disk_files": ["file-1.txt"],
    "disk_reads": 1,
    "disk_writes": 0
  }
}
```

The example omits some response fields for readability. Use `/docs` for the complete response models.

## Paired policy comparison

`POST /api/benchmarks/compare`

```json
{
  "capacity_bytes": 256,
  "workload": "skewed_popularity",
  "request_count": 500,
  "seed": 2026,
  "file_count": 100,
  "hot_set_size": 5,
  "read_latency_seconds": 0.005,
  "write_latency_seconds": 0.01,
  "read_cost": 1.0,
  "write_cost": 2.0
}
```

The `hit_ratio` metric is the read hit ratio. `hits`/`misses` count read outcomes; `write_hits`/`write_misses` count write-allocation outcomes. Overall `requests` also includes deletes and flushes. Response includes `seed`, `workload`, `request_count`, `capacity_bytes`, `trace_fingerprint`, `same_trace_for_both_policies`, and `policies.lru` / `policies.adaptive`. Each policy result includes metrics, diagnostics, final MRU-to-LRU keys, and outcome count. The trace fingerprint identifies the generated request sequence; paired fairness comes from reusing the same trace and initial files.

## Export

- `GET /api/simulations/{simulation_id}/export?format=json`
- `GET /api/simulations/{simulation_id}/export?format=csv`

The response is an attachment. JSON contains config-derived result fields, metrics, final cache/disk keys, diagnostics, and per-request outcomes. CSV contains one row per request, including operation, hit/miss, admission/bypass, evictions, write-backs, byte occupancy, I/O deltas, measured execution seconds, modeled storage seconds/cost, and error field.

## Errors and lifecycle

- `422 Unprocessable Entity`: invalid field, out-of-range value, extra field, or `hot_set_size > file_count`.
- `404 Not Found`: unknown/expired/nonexistent in-process simulation ID.
- `503 Service Unavailable`: session capacity reached (128 sessions) or benchmark concurrency is saturated, as applicable.
- Sessions live only in server memory and disappear on restart. There is no authentication or persistent session store; bind to localhost for local evaluation rather than exposing the development server publicly.

## Delete a simulation session

`DELETE /api/simulations/{simulation_id}` releases that simulation's in-memory state and recorded request trace, returning `{"simulation_id":"...","deleted":true}`. Subsequent requests for the deleted identifier return HTTP 404. The active dashboard run is cleaned up when a replacement simulation is created.
