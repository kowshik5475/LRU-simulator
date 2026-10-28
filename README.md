# Custom LRU-Based Adaptive File Cache Simulator

An educational, end-to-end simulator for exploring byte-capacity file caching, replacement policies, write-back behavior, reproducible workloads, and policy comparisons. The project includes a Python engine and CLI, a FastAPI service, and a React + TypeScript dashboard.

> **Scope:** the “disk” is an in-memory `SimulatedDisk` dictionary. This project does not intercept, benchmark, or modify physical disk I/O, OS page-cache behavior, or real filesystem operations.

## Goals and features

- Standard LRU reference policy and a configurable, scan-resistant probationary/protected policy.
- UTF-8 byte-based capacity accounting, oversized-file bypass, dirty/write-back behavior, and explicit `flush()`.
- Deterministic workload generation from seeds: sequential scan, hot set, uniform random, skewed popularity, changing hot set, and mixed-size I/O.
- Step/run simulation controls, read hit/miss metrics, separate write-hit/write-miss counters, and policy diagnostics.
- Paired policy comparison over the same request trace and initial simulated-disk contents, with a trace fingerprint.
- FastAPI validation, state endpoints, JSON/CSV exports, and OpenAPI docs.
- React dashboard for simulation, workload exploration, policy comparison, charts, and exports.
- Python unit/integration/API/benchmark tests plus a live HTTP smoke script.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the diagram and component responsibilities. The Python `SimulationEngine` is the source of truth for cache behavior; the API serializes and coordinates it rather than implementing a second algorithm.

## Requirements

- Python 3.9 or newer (the checked-in benchmark manifest was generated with Python 3.13.5).
- Node.js and npm compatible with the versions required by Vite 6 / TypeScript 5.6 for the dashboard.
- Optional: `curl` for the API examples.
- No external database or physical storage device is needed.

## Installation

From the repository root:

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[api,dev]"
```

Install the frontend dependencies separately:

```bash
cd frontend
npm install
cp .env.example .env.local   # Windows: copy .env.example .env.local
cd ..
```

The frontend config `VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000` in the example. Keep `.env.local` local; it is ignored by Git.

## Run locally

Open two terminals from the repository root.

**Terminal A — backend API:**

```bash
# Activate .venv first if needed
PYTHONPATH=src uvicorn filecache_sim.api:app --host 127.0.0.1 --port 8000 --reload
```

- Health: http://127.0.0.1:8000/api/health
- Interactive OpenAPI docs: http://127.0.0.1:8000/docs

**Terminal B — dashboard:**

```bash
cd frontend
npm run dev
```

Open the URL Vite prints (normally http://127.0.0.1:5173). The API CORS allowlist is configured for the local development origins in `src/filecache_sim/api.py`.

## Python CLI

After installation:

```bash
filecache-sim --help
filecache-sim demo --capacity 64 --policy lru
filecache-sim demo --capacity 64 --policy adaptive
filecache-sim shell --capacity 100 --policy adaptive
```

From a source checkout without installing the package:

```bash
PYTHONPATH=src python -m filecache_sim.cli demo --capacity 64 --policy lru
PYTHONPATH=src python -m filecache_sim.cli demo --capacity 64 --policy adaptive
```

The interactive shell supports `read <file>`, `write <file> <text>`, `delete <file>`, `flush`, `show`, `stats`, `ls`, and `exit`.

## Reproduce checks and benchmark data

```bash
python -m pytest -q
python -m pytest -q tests/test_api.py tests/test_integration_smoke.py
python -m compileall -q src tests scripts benchmarks
python scripts/smoke_api.py
PYTHONPATH=src python benchmarks/benchmark_suite.py --smoke --output-dir benchmark-results/reproduced-smoke
```

For the full five-seed benchmark, see [docs/BENCHMARKS.md](docs/BENCHMARKS.md). Test inventory and recorded outcomes are in [docs/TESTING.md](docs/TESTING.md). Existing generated results under `benchmark-results/full/` and `benchmark-results/smoke/` are retained as evidence; reproduce into a different output directory to avoid overwriting them.

## Documentation

- [Architecture diagram](docs/ARCHITECTURE.md)
- [Algorithm and design report](docs/REPORT.md)
- [Testing and verification](docs/TESTING.md)
- [Final repository audit](docs/FINAL_AUDIT.md)
- [Benchmark methodology and findings](docs/BENCHMARKS.md)
- [HTTP API reference](docs/API.md)
- [Short demo script](docs/DEMO.md)
- [LinkedIn portfolio draft](docs/LINKEDIN_POST.md)

## Important limitations

- Storage and disk counters are simulated in memory; they are not measurements of physical I/O.
- The API stores simulation sessions in process memory (up to a configured cap) and does not persist sessions across server restarts.
- The adaptive policy is a project-specific combination inspired by established segmented-LRU / 2Q-style ideas, not a claim of a novel caching algorithm.
- Workload results depend on the generated traces, file sizes, seed, and capacity. No policy is universally best.
- Benchmark wall-clock measurements include Python and instrumentation overhead, are machine-sensitive, and should not be interpreted as physical-storage performance.
- Frontend browser behavior requires a successful `npm install`; use the frontend typecheck/build commands below when dependencies are available.

## License

MIT. See [LICENSE](LICENSE).
