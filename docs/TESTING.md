# Testing and Verification Record

## Reproduce locally

Activate the virtual environment and install the development/API extras:

```bash
python -m pip install -e ".[api,dev]"
python -m pytest -q
python -m pytest -q tests/test_api.py
python -m pytest -q tests/test_api.py tests/test_integration_smoke.py
python -m pytest -q tests/test_benchmark_suite.py tests/test_integration_smoke.py
python -m compileall -q src tests scripts benchmarks
python scripts/smoke_api.py
```

CLI checks:

```bash
PYTHONPATH=src python -m filecache_sim.cli --help
PYTHONPATH=src python -m filecache_sim.cli demo --capacity 64 --policy lru
PYTHONPATH=src python -m filecache_sim.cli demo --capacity 64 --policy adaptive
```

Frontend checks (from `frontend/`, after `npm install`):

```bash
npm run typecheck
npm run build
```

There is currently no configured frontend lint script (`npm run` lists the available scripts). The browser dashboard should be manually smoke-tested after starting the API and Vite server as described in the root README.

## Recorded backend results

The integration pass recorded in the development environment produced:

| Command | Recorded result |
|---|---|
| `python -m pytest -q` | **Exit 0; 74 passed** |
| `python -m pytest -q tests/test_api.py` | **Exit 0; 12 passed** |
| `python -m pytest -q tests/test_api.py tests/test_integration_smoke.py` | **Exit 0; 15 passed** |
| `python -m pytest -q tests/test_benchmark_suite.py tests/test_integration_smoke.py` | **Exit 0; 7 passed** |
| `python -m compileall -q src tests scripts benchmarks` | **Exit 0** |
| `python scripts/smoke_api.py` | **Exit 0; live HTTP smoke passed** |
| LRU CLI demo | **Exit 0** |
| Adaptive CLI demo | **Exit 0** |
| Full benchmark suite (five seeds, 500 requests, four capacities) | **Exit 0; 140 paired-policy result rows; aggregate metrics matched the checked-in summary data** |
| TypeScript/TSX syntax transpile (5 source files) | **Pass; syntax only, not a typecheck/build** |

The full suite includes cache behavior, policy behavior, CLI, simulation/workload behavior, API validation, benchmark determinism, read-hit-ratio semantics, and integration checks. The integration tests verify step/state consistency, byte accounting, run/export paths, paired comparison trace fingerprints, and invalid-input handling.

The checked-in smoke artifacts under `benchmark-results/smoke/` were regenerated and contain 20 paired-policy result rows (seed 2026, 30 requests per trace). To reproduce without overwriting the checked-in artifacts, run `PYTHONPATH=src python benchmarks/benchmark_suite.py --smoke --output-dir /tmp/cachelab-reproduced`; outputs are written under `/tmp/cachelab-reproduced/smoke/`. The live HTTP smoke script starts a local Uvicorn server and checks health, simulation creation, stepping, state refresh, full run, JSON/CSV export, paired comparison reproducibility, and HTTP 422 validation. The recorded output reported 12 engine requests and trace fingerprint `be2b70271d947f24b40e8e0dbdcbae5473d0c3db72e6f6a2c261695ada7c75ea` for that smoke configuration. A new configuration or implementation can produce a different fingerprint.

## Frontend verification caveat

During this final audit, `npm install --no-audit --no-fund` timed out after 180 seconds and frontend dependencies remained unavailable in this environment. A TypeScript transpile-only check passed for the five `.ts`/`.tsx` source files; this checks syntax but **is not** equivalent to a full TypeScript typecheck, production bundle, or browser E2E test. The frontend typecheck, production build, and browser-level E2E test therefore remain **unverified**. Re-run `npm install`, `npm run typecheck`, and `npm run build` on a network-enabled machine before representing the dashboard as fully verified. There is no configured frontend lint script.

An unrelated environment-level warning was emitted by the Python execution wrapper during prior checks (`artifact_tool.rpc.client.RemoteError: Element ordering requires an owning element collection.`). The listed Python commands nevertheless returned exit code 0; this warning was not traced to project code.
