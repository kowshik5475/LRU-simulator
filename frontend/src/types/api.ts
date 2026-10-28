export type Policy = 'lru' | 'adaptive'
export type Workload =
  | 'sequential_scan'
  | 'hot_set'
  | 'uniform_random'
  | 'skewed_popularity'
  | 'changing_hot_set'
  | 'mixed_sizes_io'

export interface SimulationConfig {
  capacity_bytes: number
  policy: Policy
  workload: Workload
  request_count: number
  seed: number
  file_count: number
  hot_set_size: number
  read_latency_seconds: number
  write_latency_seconds: number
  read_cost: number
  write_cost: number
}
export type MetricSet = Record<string, number>
export interface CacheEntry {
  name: string
  content: string
  size_bytes: number
  dirty: boolean
  recency_rank: number
}
export interface Request {
  operation: 'read' | 'write' | 'delete' | 'flush'
  name?: string | null
  content?: string | null
}
export interface RequestOutcome {
  index: number
  request: Request
  hit: boolean | null
  miss: boolean | null
  admitted: boolean
  bypassed: boolean
  promotions: number
  scan_related_decisions: number
  evicted: string[]
  write_backs: string[]
  result?: string | null
  error?: string | null
  cache_used_bytes: number
  capacity_bytes: number
  disk_reads_delta: number
  disk_writes_delta: number
  elapsed_seconds: number
  simulated_storage_seconds: number
  simulated_cost: number
  policy_diagnostics: Record<string, number | string>
}
export interface SimulationState {
  simulation_id: string
  status: 'ready' | 'running' | 'completed'
  config: SimulationConfig
  next_request_index: number
  total_requests: number
  done: boolean
  cache_entries_mru_to_lru: CacheEntry[]
  recency_order_mru_to_lru: string[]
  used_bytes: number
  capacity_bytes: number
  capacity_utilization: number
  metrics: MetricSet
  policy_diagnostics: Record<string, number | string>
  disk_files: string[]
  disk_reads: number
  disk_writes: number
  last_outcome: RequestOutcome | null
}
export interface SimulationCreated {
  simulation_id: string
  status: 'ready'
  config: SimulationConfig
  request_count: number
  created_at: string
}
export interface StepResponse {
  simulation_id: string
  status: 'ready' | 'completed'
  done: boolean
  outcome: RequestOutcome | null
  state: SimulationState
}
export interface BenchmarkPolicyResult {
  policy: Policy
  metrics: MetricSet
  policy_diagnostics: Record<string, number | string>
  final_cache_keys_mru_to_lru: string[]
  outcomes_recorded: number
}
export interface BenchmarkCompareResponse {
  seed: number
  workload: Workload
  request_count: number
  capacity_bytes: number
  trace_fingerprint: string
  same_trace_for_both_policies: boolean
  policies: Record<Policy, BenchmarkPolicyResult>
}
export interface HealthResponse {
  status: 'ok'
  version: string
  engine: string
  storage: string
}
