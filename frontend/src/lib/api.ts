import type {
  BenchmarkCompareResponse, HealthResponse, SimulationConfig, SimulationCreated,
  SimulationState, StepResponse,
} from '../types/api'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
      signal: init?.signal ?? AbortSignal.timeout(120_000),
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error('The request timed out. The simulation may be large; try fewer requests or check the backend.')
    }
    throw new Error(`Cannot reach the CacheLab API at ${API_BASE}. Start the FastAPI server and try again.`)
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch { /* non-JSON error response */ }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  createSimulation: (config: SimulationConfig) => request<SimulationCreated>('/api/simulations', {
    method: 'POST', body: JSON.stringify(config),
  }),
  run: (id: string) => request<SimulationState>(`/api/simulations/${id}/run`, { method: 'POST' }),
  step: (id: string) => request<StepResponse>(`/api/simulations/${id}/step`, { method: 'POST' }),
  state: (id: string) => request<SimulationState>(`/api/simulations/${id}/state`),
  deleteSimulation: (id: string) => request<{ simulation_id: string; deleted: true }>(`/api/simulations/${id}`, { method: 'DELETE' }),
  compare: (config: Omit<SimulationConfig, 'policy'>) => request<BenchmarkCompareResponse>('/api/benchmarks/compare', {
    method: 'POST', body: JSON.stringify(config),
  }),
  export: async (id: string, format: 'json' | 'csv') => {
    let response: Response
    try {
      response = await fetch(`${API_BASE}/api/simulations/${id}/export?format=${format}`, {
        signal: AbortSignal.timeout(120_000),
      })
    } catch {
      throw new Error(`Cannot reach the CacheLab API at ${API_BASE}. Start the FastAPI server and try again.`)
    }
    if (!response.ok) {
      let message = `Export failed (${response.status})`
      try { const body = await response.json() as { detail?: string }; message = body.detail ?? message } catch { /* ignore */ }
      throw new ApiError(message, response.status)
    }
    return { blob: await response.blob(), filename: `cachelab-${id}.${format}` }
  },
}
