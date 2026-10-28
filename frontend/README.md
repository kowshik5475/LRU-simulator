# CacheLab frontend

CacheLab is a React + TypeScript dashboard for the existing Python FastAPI cache
simulator. It does not implement caching or fabricate metrics: cache state,
request outcomes, comparison results, and exports come from the backend.

## Requirements

- Node.js 20 or newer (tested target: Node 22)
- npm 10 or newer
- The repository's FastAPI backend running at `http://127.0.0.1:8000`

## Install and run

From this directory:

```bash
npm install
cp .env.example .env.local
npm run dev
```

Open `http://127.0.0.1:5173`. The development origin is allowed by the backend's
explicit CORS configuration. Override `VITE_API_BASE_URL` in `.env.local` if the
API is hosted elsewhere.

Start the backend from the repository root in another terminal:

```bash
python -m pip install -e ".[api,dev]"
PYTHONPATH=src uvicorn filecache_sim.api:app --host 127.0.0.1 --port 8000
```

## Checks

```bash
npm run typecheck
npm run build
npm run preview
```

The production bundle is written to `dist/`. Do not commit `.env.local` or
secrets. The dashboard currently uses a single local in-memory simulation
session per selected run; backend state is authoritative.

## API usage

The typed client is in `src/lib/api.ts`, and response contracts are in
`src/types/api.ts`. It calls:

- `GET /api/health`
- `POST /api/simulations`
- `POST /api/simulations/{id}/run`
- `POST /api/simulations/{id}/step`
- `GET /api/simulations/{id}/state`
- `DELETE /api/simulations/{id}` (release the active in-memory session)
- `POST /api/benchmarks/compare`
- `GET /api/simulations/{id}/export?format=csv|json`

The backend currently supports step-by-step execution and run-to-completion.
Pause/resume is not exposed by its API, so the UI explains this rather than
pretending a full run can be paused.
