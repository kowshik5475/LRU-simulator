# 3-minute project demonstration

## Setup

Terminal 1:

```bash
PYTHONPATH=src uvicorn filecache_sim.api:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL and walk through the dashboard. If frontend dependencies are not installed, use the reproducible CLI/API demo below.

## Suggested narration

1. **Problem (20 sec):** “This is a simulator for how file-cache replacement policies behave under different access traces. It uses a byte-bounded cache and an in-memory simulated disk, not real physical disk I/O.”
2. **Baseline vs adaptive (40 sec):** select Standard LRU and Adaptive LRU. Explain that standard LRU evicts the globally least-recently-used entry; adaptive policy keeps probationary and protected segments and prefers probationary LRU for eviction.
3. **Step-by-step (30 sec):** create a short seeded workload, step one request, and show hit/miss, cache occupancy, recency, and diagnostics update from the API.
4. **Fair comparison (40 sec):** compare policies with the same workload seed and capacity. Point out that matching traces make the comparison fairer, but one seed/workload does not prove general superiority.
5. **Results/export (30 sec):** inspect charts/metrics and export JSON or CSV. Explain measured Python execution time vs modeled storage latency/cost.
6. **Evidence (20 sec):** show `docs/TESTING.md` and `docs/BENCHMARKS.md`; state exact test count and caveat that frontend production build needs a successful dependency install if not yet verified.

## Backend-only reproducible smoke

```bash
python -m pip install -e ".[api,dev]"
python scripts/smoke_api.py
```

This script launches a real local Uvicorn process and exercises HTTP endpoints against the Python engine. It is a smoke test, not a browser-based end-to-end test.
