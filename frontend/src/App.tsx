import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, Check, ChevronDown, CircleHelp,
  Clock3, Command, Database, Download, FileJson, FileSpreadsheet, FlaskConical,
  Gauge, HardDrive, Layers3, ListOrdered, Play, RefreshCw, Search,
  Server, Settings2, ShieldCheck, SkipForward, Sparkles, Target, Zap,
} from 'lucide-react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from './lib/api'
import type {
  BenchmarkCompareResponse, MetricSet, Policy, RequestOutcome, SimulationConfig,
  SimulationState, Workload,
} from './types/api'
import { Button, Card, EmptyState, ErrorBanner, HealthNotice, MetricCard, StatusPill } from './components/Primitives'

type Page = 'overview' | 'simulator' | 'workloads' | 'compare' | 'results'
const nav: { id: Page; label: string; icon: typeof Activity; group: string }[] = [
  { id: 'overview', label: 'Overview', icon: Gauge, group: 'WORKSPACE' },
  { id: 'simulator', label: 'Simulator', icon: Layers3, group: 'WORKSPACE' },
  { id: 'workloads', label: 'Workload lab', icon: FlaskConical, group: 'EXPERIMENTS' },
  { id: 'compare', label: 'Algorithm compare', icon: BarChart3, group: 'EXPERIMENTS' },
  { id: 'results', label: 'Results & export', icon: FileSpreadsheet, group: 'DATA' },
]
const workloadOptions: { value: Workload; label: string; description: string }[] = [
  { value: 'sequential_scan', label: 'Sequential scan', description: 'Walk a file set once to reveal scan pollution and eviction churn.' },
  { value: 'hot_set', label: 'Repeated hot set', description: 'Revisit a compact working set to measure retention of frequently used files.' },
  { value: 'uniform_random', label: 'Uniform random', description: 'Every file has equal selection probability.' },
  { value: 'skewed_popularity', label: 'Skewed popularity', description: 'A small subset receives a larger share of requests.' },
  { value: 'changing_hot_set', label: 'Changing hot set', description: 'The popular working set shifts over the request trace.' },
  { value: 'mixed_sizes_io', label: 'Mixed sizes & I/O', description: 'Mix file sizes and reads/writes to stress byte capacity and dirty eviction.' },
]
const defaults: SimulationConfig = {
  capacity_bytes: 256, policy: 'lru', workload: 'hot_set', request_count: 500, seed: 2026,
  file_count: 100, hot_set_size: 5, read_latency_seconds: 0.005, write_latency_seconds: 0.01,
  read_cost: 1, write_cost: 2,
}
const fmt = (n: number | undefined, digits = 1) => Number.isFinite(n) ? (n as number).toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
const pct = (n: number | undefined) => `${fmt((n ?? 0) * 100, 1)}%`
const shortTime = (seconds: number | undefined) => seconds == null ? '—' : seconds < 0.001 ? `${(seconds * 1e6).toFixed(0)} μs` : `${(seconds * 1000).toFixed(2)} ms`
const errorMessage = (e: unknown) => e instanceof Error ? e.message : 'Something went wrong. Please try again.'
const metric = (m: MetricSet | undefined, key: string) => m?.[key] ?? 0

function App() {
  const [page, setPage] = useState<Page>('overview')
  const [config, setConfig] = useState<SimulationConfig>(defaults)
  const [state, setState] = useState<SimulationState | null>(null)
  const [simulationId, setSimulationId] = useState<string | null>(null)
  const [events, setEvents] = useState<RequestOutcome[]>([])
  const [comparison, setComparison] = useState<BenchmarkCompareResponse | null>(null)
  const [online, setOnline] = useState(false)
  const [apiVersion, setApiVersion] = useState<string>()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'create' | 'run' | 'step' | 'compare' | 'export' | null>(null)
  const [mobileNav, setMobileNav] = useState(false)

  const checkHealth = useCallback(async () => {
    try { const h = await api.health(); setOnline(true); setApiVersion(h.version) }
    catch { setOnline(false); setApiVersion(undefined) }
  }, [])
  useEffect(() => { void checkHealth(); const timer = window.setInterval(() => void checkHealth(), 15000); return () => window.clearInterval(timer) }, [checkHealth])

  const patchConfig = (patch: Partial<SimulationConfig>) => setConfig(prev => ({ ...prev, ...patch }))
  const refreshHistory = useCallback(async (id: string) => {
    try {
      const { blob } = await api.export(id, 'json')
      const data = JSON.parse(await blob.text()) as { outcomes?: RequestOutcome[] }
      setEvents(data.outcomes ?? [])
    } catch { /* state remains authoritative even if optional event history refresh fails */ }
  }, [])

  const create = useCallback(async (overrides: Partial<SimulationConfig> = {}) => {
    setBusy('create'); setError(null)
    const nextConfig = { ...config, ...overrides }
    const previousId = simulationId
    let createdId: string | null = null
    try {
      const created = await api.createSimulation(nextConfig)
      createdId = created.simulation_id
      const freshState = await api.state(createdId)
      setConfig(nextConfig); setSimulationId(createdId); setState(freshState); setEvents([]); setPage('simulator')
      // Keep only the active run in this browser session to avoid exhausting
      // the backend's bounded in-memory session store during repeated experiments.
      if (previousId && previousId !== createdId) {
        void api.deleteSimulation(previousId).catch(() => { /* backend may have restarted */ })
      }
      return createdId
    } catch (e) {
      if (createdId) void api.deleteSimulation(createdId).catch(() => { /* best-effort cleanup */ })
      setError(errorMessage(e)); return null
    }
    finally { setBusy(null) }
  }, [config, simulationId])

  const ensureSimulation = useCallback(async () => {
    const configMatches = state && JSON.stringify(state.config) === JSON.stringify(config)
    if (simulationId && state && !state.done && configMatches) return simulationId
    return create()
  }, [simulationId, state, config, create])

  const run = useCallback(async () => {
    setError(null)
    let id = simulationId
    const configMatches = state && JSON.stringify(state.config) === JSON.stringify(config)
    if (!id || state?.done || !configMatches) id = await create()
    if (!id) return
    setBusy('run')
    try {
      const next = await api.run(id)
      setState(next); await refreshHistory(id)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(null) }
  }, [simulationId, state, config, create, refreshHistory])

  const step = useCallback(async () => {
    setError(null)
    let id = await ensureSimulation()
    if (!id) return
    setBusy('step')
    try {
      const result = await api.step(id)
      setState(result.state)
      if (result.outcome) setEvents(previous => [...previous, result.outcome as RequestOutcome])
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(null) }
  }, [ensureSimulation])

  const reset = useCallback(async () => { await create() }, [create])

  const compare = useCallback(async () => {
    setBusy('compare'); setError(null)
    try {
      const { policy: _policy, ...comparisonConfig } = config
      void _policy
      const result = await api.compare(comparisonConfig)
      setComparison(result)
      setPage('compare')
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(null) }
  }, [config])

  const exportFile = useCallback(async (format: 'json' | 'csv') => {
    if (!simulationId) { setError('Create a simulation before exporting results.'); return }
    setBusy('export'); setError(null)
    try {
      const file = await api.export(simulationId, format)
      const url = URL.createObjectURL(file.blob)
      const link = document.createElement('a'); link.href = url; link.download = file.filename
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(null) }
  }, [simulationId])

  const chartData = useMemo(() => events.slice(-60).map(o => ({
    request: o.index + 1, occupied: o.cache_used_bytes, hits: o.hit ? 1 : 0,
    misses: o.miss ? 1 : 0, capacity: o.capacity_bytes,
  })), [events])
  const activityRows = [...events].slice(-7).reverse()

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Command size={20} strokeWidth={2.5}/></div><div><div className="brand-name">Cache<span>Lab</span></div><div className="brand-caption">CACHE SIMULATION STUDIO</div></div><button className="mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation">×</button></div>
      <div className="workspace-switch"><div className="workspace-avatar">CL</div><div className="workspace-text"><strong>Local workspace</strong><span>Python simulation engine</span></div><ChevronDown size={15}/></div>
      {['WORKSPACE', 'EXPERIMENTS', 'DATA'].map(group => <div className="nav-group" key={group}><div className="nav-group-label">{group}</div>{nav.filter(item => item.group === group).map(item => {
        const Icon = item.icon
        return <button key={item.id} onClick={() => { setPage(item.id); setMobileNav(false) }} className={`nav-item ${page === item.id ? 'nav-item-active' : ''}`} aria-current={page === item.id ? 'page' : undefined}><Icon size={17}/><span>{item.label}</span>{item.id === 'compare' && comparison && <span className="nav-indicator"/>}</button>
      })}</div>)}
      <div className="sidebar-spacer"/>
      <div className="sidebar-bottom">
        <div className="engine-card"><div className="engine-icon"><Server size={16}/></div><div><strong>Simulation engine</strong><span>Python · In-memory disk</span></div><span className={`engine-dot ${online ? 'dot-online' : ''}`}/></div>
        <HealthNotice online={online} version={apiVersion}/>
        <div className="sidebar-footer"><span>CacheLab <span className="version-chip">v1.0</span></span><span>Built for experiments</span></div>
      </div>
    </aside>
    {mobileNav && <button className="mobile-scrim" onClick={() => setMobileNav(false)} aria-label="Close menu"/>}
    <main className="main-content">
      <header className="topbar">
        <div className="topbar-left"><button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Command size={20}/></button><div className="breadcrumbs"><span>CacheLab</span><span className="crumb-slash">/</span><strong>{nav.find(n => n.id === page)?.label}</strong></div></div>
        <div className="topbar-right"><div className="seed-display"><span className="seed-dot"/><span>Seed</span><strong>{config.seed}</strong></div><div className="avatar">E</div></div>
      </header>
      <div className="page-wrap">
        {error && <ErrorBanner message={error} onDismiss={() => setError(null)}/>}
        {!online && <div className="connection-banner"><WifiOffIcon/><span>Backend unavailable. Start the FastAPI server to load real simulation data.</span><button onClick={() => void checkHealth()}>Retry connection</button></div>}
        {page === 'overview' && <Overview state={state} events={activityRows} onNavigate={setPage} onRun={run} busy={busy} chartData={chartData}/>}
        {page === 'simulator' && <Simulator config={config} patchConfig={patchConfig} state={state} busy={busy} onRun={run} onStep={step} onReset={reset} events={events} onExport={exportFile}/>}
        {page === 'workloads' && <Workloads config={config} patchConfig={patchConfig} onCreate={create} onCompare={compare} busy={busy}/>}
        {page === 'compare' && <Compare config={config} patchConfig={patchConfig} comparison={comparison} onCompare={compare} busy={busy}/>}
        {page === 'results' && <Results state={state} events={events} busy={busy} onExport={exportFile} onNavigate={setPage}/>}
        <footer className="page-footer"><span>CacheLab <span className="footer-dot">·</span> Reproducible cache experiments</span><span>All cache logic runs in Python <span className="footer-dot">·</span> Simulated storage only</span></footer>
      </div>
    </main>
  </div>
}

function WifiOffIcon() { return <Activity size={16}/> }

function PageTitle({ eyebrow, title, subtitle, action }: { eyebrow: string; title: string; subtitle: string; action?: ReactNode }) {
  return <div className="page-title-row"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="page-title-action">{action}</div>}</div>
}

function Overview({ state, events, onNavigate, onRun, busy, chartData }: {
  state: SimulationState | null; events: RequestOutcome[]; onNavigate: (p: Page) => void; onRun: () => void; busy: string | null; chartData: {request:number;occupied:number;capacity:number;hits:number;misses:number}[]
}) {
  const m = state?.metrics
  return <div className="page-stack">
    <PageTitle eyebrow="WORKSPACE / OVERVIEW" title="Cache at a glance" subtitle="A live view of cache behavior, workload progress, and storage activity." action={<Button onClick={onRun} disabled={!!busy}><Play size={15} fill="currentColor"/>{busy === 'run' ? 'Running…' : 'Run simulation'}</Button>}/>
    {!state ? <Card><EmptyState icon={<Database size={26}/>} title="No simulation loaded" description="Create a simulation to populate this dashboard with real cache metrics and request activity." action={<Button onClick={() => onNavigate('simulator')}><Sparkles size={15}/> Configure simulator</Button>}/></Card> : <>
      <div className="context-strip"><div className="context-left"><div className="context-icon"><Activity size={16}/></div><div><strong>{state.config.workload.replaceAll('_',' ')}</strong><span>{state.config.policy === 'lru' ? 'Standard LRU' : 'Adaptive LRU'} · Seed {state.config.seed} · {state.next_request_index.toLocaleString()} of {state.total_requests.toLocaleString()} requests</span></div></div><StatusPill tone={state.done ? 'green' : 'blue'}>{state.done ? 'Completed' : 'In progress'}</StatusPill></div>
      <div className="metrics-grid">
        <MetricCard label="Read hit ratio" value={pct(m?.hit_ratio)} detail={`${fmt(metric(m,'hits'),0)} read hits`} icon={<Target size={18}/>} accent="green"/>
        <MetricCard label="Miss ratio" value={pct((m?.hits ?? 0)+(m?.misses ?? 0) ? (m?.misses ?? 0)/((m?.hits ?? 0)+(m?.misses ?? 0)) : 0)} detail={`${fmt(metric(m,'misses'),0)} disk lookups`} icon={<Search size={18}/>} accent="orange"/>
        <MetricCard label="Cache occupancy" value={`${fmt(state.used_bytes,0)} B`} detail={`${fmt(state.capacity_utilization*100,1)}% of ${fmt(state.capacity_bytes,0)} B`} icon={<Layers3 size={18}/>} accent="violet"/>
        <MetricCard label="Evictions" value={fmt(metric(m,'evictions'),0)} detail={`${fmt(metric(m,'write_backs'),0)} write-backs`} icon={<ArrowDownRight size={18}/>} accent="cyan"/>
      </div>
      <div className="two-col-grid">
        <Card className="chart-card"><div className="card-heading"><div><h3>Cache occupancy</h3><p>Used bytes across executed requests</p></div><span className="chart-legend"><span className="legend-dot violet-dot"/>Occupied</span></div>{chartData.length ? <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData}><defs><linearGradient id="occupancyGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8b7cff" stopOpacity={0.3}/><stop offset="100%" stopColor="#8b7cff" stopOpacity={0.01}/></linearGradient></defs><CartesianGrid stroke="#20283a" strokeDasharray="3 3" vertical={false}/><XAxis dataKey="request" stroke="#69758b" tickLine={false} axisLine={false} tick={{fontSize:11}}/><YAxis stroke="#69758b" tickLine={false} axisLine={false} tick={{fontSize:11}} width={42}/><Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v} B`, 'Occupied']}/><Area type="monotone" dataKey="occupied" stroke="#998bff" strokeWidth={2} fill="url(#occupancyGradient)" isAnimationActive={false}/></AreaChart></ResponsiveContainer></div> : <ChartEmpty text="Step through or run a simulation to chart occupancy."/>}</Card>
        <Card className="disk-card"><div className="card-heading"><div><h3>Storage operations</h3><p>Simulated disk activity</p></div><div className="disk-icon"><HardDrive size={17}/></div></div><div className="disk-stats"><div><span className="disk-stat-label">Disk reads</span><strong>{fmt(state.disk_reads,0)}</strong><span className="disk-stat-foot"><ArrowDownRight size={13}/> Read operations</span></div><div><span className="disk-stat-label">Disk writes</span><strong>{fmt(state.disk_writes,0)}</strong><span className="disk-stat-foot"><ArrowUpRight size={13}/> Write operations</span></div></div><div className="divider"/><div className="detail-list"><div><span>Admissions</span><strong>{fmt(metric(m,'admissions'),0)}</strong></div><div><span>Promotions</span><strong>{fmt(metric(m,'promotions'),0)}</strong></div><div><span>Bypasses</span><strong>{fmt(metric(m,'bypasses'),0)}</strong></div><div><span>Actual Python time</span><strong>{shortTime(metric(m,'actual_execution_seconds'))}</strong></div></div><div className="info-note"><CircleHelp size={14}/> Simulated storage latency is modeled separately from actual execution time.</div></Card>
      </div>
      <div className="bottom-grid">
        <Card className="activity-card"><div className="card-heading"><div><h3>Recent activity</h3><p>Latest observed request outcomes from the Python engine</p></div><button className="text-link" onClick={() => onNavigate('results')}>View all <ArrowUpRight size={13}/></button></div>{events.length ? <div className="event-list">{events.map((event) => <EventRow event={event} key={`${event.index}-${event.request.operation}`}/>)}</div> : <ChartEmpty text="No request events yet. Run or step through the simulator."/>}</Card>
        <Card className="quick-card"><div className="card-heading"><div><h3>Quick actions</h3><p>Continue your experiment</p></div></div><button className="quick-action" onClick={() => onNavigate('simulator')}><div className="quick-icon violet-bg"><Layers3 size={16}/></div><span><strong>Open simulator</strong><small>Inspect cache entries and step requests</small></span><ArrowUpRight size={15}/></button><button className="quick-action" onClick={() => onNavigate('workloads')}><div className="quick-icon cyan-bg"><FlaskConical size={16}/></div><span><strong>Configure workload</strong><small>Explore six synthetic request patterns</small></span><ArrowUpRight size={15}/></button><button className="quick-action" onClick={() => onNavigate('compare')}><div className="quick-icon green-bg"><BarChart3 size={16}/></div><span><strong>Compare algorithms</strong><small>Run both policies on the same trace</small></span><ArrowUpRight size={15}/></button></Card>
      </div>
    </>}
  </div>
}

const tooltipStyle = { backgroundColor: '#111827', border: '1px solid #303a4f', borderRadius: 10, color: '#f2f4fa', fontSize: 12 }
function ChartEmpty({ text }: { text: string }) { return <div className="chart-empty"><BarChart3 size={23}/><span>{text}</span></div> }

function EventRow({ event }: { event: RequestOutcome }) {
  const hit = event.hit === true
  const miss = event.miss === true
  const label = event.error ? 'Error' : event.bypassed ? 'Bypass' : event.promotions > 0 ? 'Promotion' : event.evicted.length ? 'Eviction' : event.admitted ? 'Admission' : hit ? 'Hit' : miss ? 'Miss' : event.request.operation
  const tone = event.error ? 'red' : hit ? 'green' : event.bypassed || event.evicted.length ? 'amber' : miss ? 'blue' : 'neutral'
  return <div className="event-row"><div className={`event-icon ${tone}`}>{event.error ? <CircleHelp size={15}/> : hit ? <Check size={15}/> : event.request.operation === 'write' ? <ArrowUpRight size={15}/> : <ArrowDownRight size={15}/>}</div><div className="event-main"><strong>{event.request.name ?? 'Flush cache'}</strong><span>Request #{event.index + 1} · {event.request.operation}{event.evicted.length ? ` · evicted ${event.evicted.join(', ')}` : ''}{event.write_backs.length ? ` · wrote back ${event.write_backs.join(', ')}` : ''}</span></div><StatusPill tone={tone as 'red'|'green'|'amber'|'blue'|'neutral'}>{label}</StatusPill></div>
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="field"><span className="field-label">{label}</span>{children}{hint && <span className="field-hint">{hint}</span>}</label>
}
function ConfigPanel({ config, patchConfig, showPolicy = true }: { config: SimulationConfig; patchConfig: (p: Partial<SimulationConfig>) => void; showPolicy?: boolean }) {
  return <Card className="config-card"><div className="card-heading"><div><h3><Settings2 size={16}/> Configuration</h3><p>Define the simulation inputs</p></div><span className="config-tag">Python engine</span></div>
    <div className="form-grid">
      {showPolicy && <Field label="Cache policy"><select value={config.policy} onChange={e => patchConfig({policy:e.target.value as Policy})}><option value="lru">Standard LRU</option><option value="adaptive">Adaptive LRU</option></select></Field>}
      <Field label="Cache capacity" hint="UTF-8 encoded bytes"><div className="input-unit"><input type="number" min="1" max="10000000" value={config.capacity_bytes} onChange={e => patchConfig({capacity_bytes:Math.max(1, Number(e.target.value)||1)})}/><span>bytes</span></div></Field>
      <Field label="Workload"><select value={config.workload} onChange={e => patchConfig({workload:e.target.value as Workload})}>{workloadOptions.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}</select></Field>
      <Field label="Request count"><input type="number" min="0" max="20000" value={config.request_count} onChange={e => patchConfig({request_count:Math.max(0, Math.min(20000, Number(e.target.value)||0))})}/></Field>
      <Field label="Random seed"><input type="number" min="0" max="4294967295" value={config.seed} onChange={e => patchConfig({seed:Math.max(0, Math.min(4294967295, Number(e.target.value)||0))})}/></Field>
      <Field label="File count"><input type="number" min="1" max="5000" value={config.file_count} onChange={e => patchConfig({file_count:Math.max(1, Math.min(5000, Number(e.target.value)||1))})}/></Field>
      <Field label="Hot-set size"><input type="number" min="1" max={config.file_count} value={config.hot_set_size} onChange={e => patchConfig({hot_set_size:Math.max(1, Math.min(config.file_count, Number(e.target.value)||1))})}/></Field>
    </div>
    <div className="config-footer"><span><ShieldCheck size={14}/> Seeded workloads are reproducible</span><span>Max 20,000 requests</span></div>
  </Card>
}

function Simulator({ config, patchConfig, state, busy, onRun, onStep, onReset, events, onExport }: {
  config: SimulationConfig; patchConfig: (p: Partial<SimulationConfig>) => void; state: SimulationState | null; busy: string | null
  onRun: () => void; onStep: () => void; onReset: () => void; events: RequestOutcome[]; onExport: (f:'json'|'csv')=>void
}) {
  const entries = state?.cache_entries_mru_to_lru ?? []
  const [showContent, setShowContent] = useState(false)
  return <div className="page-stack">
    <PageTitle eyebrow="WORKSPACE / SIMULATOR" title="Interactive simulator" subtitle="Inspect cache state as the Python engine processes each request." action={<StatusPill tone={state?.done ? 'green' : state ? 'blue' : 'neutral'}>{state?.done ? 'Completed' : state ? 'Ready to execute' : 'Not initialized'}</StatusPill>}/>
    <div className="simulator-layout">
      <div className="simulator-main">
        <Card className="control-card"><div className="control-top"><div><div className="eyebrow">EXECUTION CONTROLS</div><h3>{state ? `${state.next_request_index} / ${state.total_requests} requests processed` : 'Configure and start a run'}</h3><p>{state ? `${fmt(state.capacity_utilization*100,1)}% capacity used · ${state.config.policy === 'lru' ? 'Standard LRU' : 'Adaptive LRU'}` : 'Create a simulation to initialize the cache and request trace.'}</p></div><div className="run-mark"><Activity size={20}/></div></div>
          {state && <div className="progress-track"><div className="progress-fill" style={{width:`${state.total_requests ? state.next_request_index/state.total_requests*100 : 100}%`}}/></div>}
          <div className="control-actions"><Button onClick={onRun} disabled={!!busy || !!state?.done}><Play size={15} fill="currentColor"/>{busy === 'run' ? 'Running workload…' : 'Run to completion'}</Button><Button variant="secondary" onClick={onStep} disabled={!!busy || !!state?.done && !!state}><SkipForward size={15}/>{busy === 'step' ? 'Stepping…' : 'Step request'}</Button><Button variant="ghost" onClick={onReset} disabled={!!busy}><RefreshCw size={15}/> Reset</Button></div>
          <div className="pause-note"><CircleHelp size={14}/> Step mode gives request-by-request control. Pause/resume of a server-side full run is not supported by the current API.</div>
        </Card>
        <Card className="cache-visual-card"><div className="card-heading"><div><h3><Layers3 size={16}/> Cache memory</h3><p>Most recently used → least recently used</p></div><div className="capacity-readout"><strong>{fmt(state?.used_bytes ?? 0,0)} <small>/ {fmt(state?.capacity_bytes ?? config.capacity_bytes,0)} B</small></strong><span>{pct(state?.capacity_utilization)}</span></div></div>
          <div className="capacity-track"><div className="capacity-fill" style={{width:`${Math.min(100,(state?.capacity_utilization ?? 0)*100)}%`}}/></div>
          {entries.length ? <div className="cache-entry-list">{entries.map((entry, i) => <div className={`cache-entry ${i===0?'entry-mru':''} ${entry.dirty?'entry-dirty':''}`} key={entry.name}><div className="entry-rank">{String(i+1).padStart(2,'0')}</div><div className="entry-file-icon"><FileJson size={17}/></div><div className="entry-info"><strong>{entry.name}</strong><span>{showContent ? entry.content : `${entry.content.slice(0,38)}${entry.content.length>38?'…':''}`}</span></div><div className="entry-size">{entry.size_bytes} B</div>{entry.dirty && <span className="dirty-pill">DIRTY</span>}<span className={`recency-pill ${i===0?'recency-hot':''}`}>{i===0?'MRU':i===entries.length-1?'LRU':`#${i+1}`}</span></div>)}</div> : <EmptyState icon={<Database size={23}/>} title="Cache is empty" description="Step or run the configured workload to populate the cache."/>}
          {entries.length>0 && <div className="cache-foot"><span>{entries.length} cached entries</span><button className="text-link" onClick={() => setShowContent(v=>!v)}>{showContent?'Hide content':'Show content'}</button><span>Dirty entries are pending write-back</span></div>}
        </Card>
        <Card className="request-chart-card"><div className="card-heading"><div><h3>Occupancy timeline</h3><p>Observed capacity after each executed request</p></div><span className="chart-legend"><span className="legend-dot violet-dot"/>Bytes used</span></div>{state && state.next_request_index>0 ? <OccupancyFromEvents events={events} capacity={state.capacity_bytes}/> : <ChartEmpty text="No requests processed yet."/>}</Card>
      </div>
      <div className="simulator-side">
        <ConfigPanel config={config} patchConfig={patchConfig}/>
        <Card className="latest-card"><div className="card-heading"><div><h3>Latest request</h3><p>Most recent API outcome</p></div><Clock3 size={17} className="muted-icon"/></div>{state?.last_outcome ? <EventRow event={state.last_outcome}/> : events.length ? <EventRow event={events[events.length-1]}/> : <div className="small-empty">Run or step to see a request outcome here.</div>}</Card>
        <Card className="policy-card"><div className="card-heading"><div><h3>Policy diagnostics</h3><p>Returned by Python policy</p></div><Zap size={16} className="muted-icon"/></div>{state ? <div className="detail-list">{Object.entries(state.policy_diagnostics).map(([key,value])=><div key={key}><span>{key.replaceAll('_',' ')}</span><strong>{value}</strong></div>)}</div> : <div className="small-empty">Diagnostics appear after a simulation is created.</div>}</Card>
        <Card className="export-mini"><div className="card-heading"><div><h3>Export this run</h3><p>Download actual API results</p></div><Download size={16} className="muted-icon"/></div><div className="export-actions"><Button variant="secondary" onClick={() => onExport('csv')} disabled={!state || busy==='export'}><FileSpreadsheet size={15}/> CSV</Button><Button variant="secondary" onClick={() => onExport('json')} disabled={!state || busy==='export'}><FileJson size={15}/> JSON</Button></div></Card>
      </div>
    </div>
  </div>
}

function OccupancyFromEvents({ events, capacity }: { events: RequestOutcome[]; capacity: number }) {
  const data = events.slice(-100).map(e=>({request:e.index+1, bytes:e.cache_used_bytes}))
  return <div className="chart-area chart-area-small"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data}><CartesianGrid stroke="#20283a" strokeDasharray="3 3" vertical={false}/><XAxis dataKey="request" stroke="#69758b" tickLine={false} axisLine={false} tick={{fontSize:10}}/><YAxis domain={[0,capacity]} stroke="#69758b" tickLine={false} axisLine={false} tick={{fontSize:10}} width={38}/><Tooltip contentStyle={tooltipStyle} formatter={(v)=>[`${v} B`,'Occupied']}/><Area dataKey="bytes" type="stepAfter" stroke="#8b7cff" fill="#8b7cff" fillOpacity={0.12} isAnimationActive={false}/></ComposedChart></ResponsiveContainer></div>
}

function Workloads({ config, patchConfig, onCreate, onCompare, busy }: { config: SimulationConfig; patchConfig:(p:Partial<SimulationConfig>)=>void; onCreate:(p?:Partial<SimulationConfig>)=>Promise<string|null>; onCompare:()=>void; busy:string|null }) {
  const selected = workloadOptions.find(w=>w.value===config.workload)!
  return <div className="page-stack"><PageTitle eyebrow="EXPERIMENTS / WORKLOAD LAB" title="Workload laboratory" subtitle="Shape a repeatable request trace before sending it to the Python engine." action={<StatusPill tone="blue"><Sparkles size={12}/> Seeded generator</StatusPill>}/>
    <div className="workload-layout"><div className="workload-list"><div className="workload-intro"><h3>Choose a workload pattern</h3><p>Each pattern produces a different request distribution. The policy sees only the resulting operations, never the workload label.</p></div>{workloadOptions.map((w,i)=><button key={w.value} onClick={()=>patchConfig({workload:w.value})} className={`workload-option ${config.workload===w.value?'workload-selected':''}`}><div className={`workload-option-icon icon-tone-${i}`}><WorkloadIcon index={i}/></div><div className="workload-option-copy"><strong>{w.label}</strong><span>{w.description}</span></div><span className={`radio-indicator ${config.workload===w.value?'radio-active':''}`}>{config.workload===w.value&&<span/>}</span></button>)}</div>
      <div className="workload-config"><Card><div className="card-heading"><div><h3>Selected workload</h3><p>Generator settings sent to FastAPI</p></div><div className="selected-count">{workloadOptions.findIndex(w=>w.value===config.workload)+1}<span> / 6</span></div></div><div className="selected-workload-hero"><div className="hero-orbit"><WorkloadIcon index={workloadOptions.findIndex(w=>w.value===config.workload)}/></div><div><div className="eyebrow">CURRENT PATTERN</div><h2>{selected.label}</h2><p>{selected.description}</p></div></div><div className="workload-facts"><div><span>Random seed</span><strong>{config.seed}</strong></div><div><span>Requests</span><strong>{config.request_count.toLocaleString()}</strong></div><div><span>File universe</span><strong>{config.file_count.toLocaleString()}</strong></div><div><span>Cache capacity</span><strong>{config.capacity_bytes} B</strong></div></div><div className="divider"/><ConfigPanel config={config} patchConfig={patchConfig} showPolicy={false}/><div className="workload-actions"><Button onClick={()=>void onCreate()} disabled={!!busy}><Play size={15} fill="currentColor"/> Create simulation</Button><Button variant="secondary" onClick={onCompare} disabled={!!busy}><BarChart3 size={15}/> Compare both policies</Button></div><p className="form-footnote">The backend validates settings and generates the trace from your seed. No frontend cache logic is used.</p></Card></div></div>
  </div>
}
function WorkloadIcon({index}:{index:number}) {
  const icons = [ListOrdered, Target, ShuffleIcon, BarChart3, RefreshCw, Database]
  const Icon = icons[index] ?? Activity
  return <Icon size={19}/>
}
function ShuffleIcon() { return <Activity size={19}/> }

function Compare({ config, patchConfig, comparison, onCompare, busy }: { config:SimulationConfig; patchConfig:(p:Partial<SimulationConfig>)=>void; comparison:BenchmarkCompareResponse|null; onCompare:()=>void; busy:string|null }) {
  const lru = comparison?.policies.lru
  const adaptive = comparison?.policies.adaptive
  const chartData = comparison ? [
    {metric:'Read hit ratio', lru:metric(lru?.metrics,'hit_ratio')*100, adaptive:metric(adaptive?.metrics,'hit_ratio')*100},
    {metric:'Evictions', lru:metric(lru?.metrics,'evictions'), adaptive:metric(adaptive?.metrics,'evictions')},
    {metric:'Write-backs', lru:metric(lru?.metrics,'write_backs'), adaptive:metric(adaptive?.metrics,'write_backs')},
    {metric:'Disk reads', lru:metric(lru?.metrics,'disk_reads'), adaptive:metric(adaptive?.metrics,'disk_reads')},
    {metric:'Disk writes', lru:metric(lru?.metrics,'disk_writes'), adaptive:metric(adaptive?.metrics,'disk_writes')},
  ] : []
  const hitDelta = lru && adaptive ? (metric(adaptive.metrics,'hit_ratio')-metric(lru.metrics,'hit_ratio'))*100 : 0
  return <div className="page-stack"><PageTitle eyebrow="EXPERIMENTS / ALGORITHM COMPARE" title="LRU vs. Adaptive LRU" subtitle="Paired experiments, identical request trace, same capacity, independent simulator state." action={<Button onClick={onCompare} disabled={!!busy}><RefreshCw size={15} className={busy==='compare'?'spin':''}/>{busy==='compare'?'Comparing…':'Run comparison'}</Button>}/>
    <Card className="compare-config"><div className="compare-config-title"><Settings2 size={16}/><strong>Experiment parameters</strong><span>Applied equally to both policies</span></div><div className="compare-fields"><Field label="Workload"><select value={config.workload} onChange={e=>patchConfig({workload:e.target.value as Workload})}>{workloadOptions.map(w=><option key={w.value} value={w.value}>{w.label}</option>)}</select></Field><Field label="Capacity (bytes)"><input type="number" min="1" max="10000000" value={config.capacity_bytes} onChange={e=>patchConfig({capacity_bytes:Math.max(1,Number(e.target.value)||1)})}/></Field><Field label="Requests"><input type="number" min="0" max="20000" value={config.request_count} onChange={e=>patchConfig({request_count:Math.max(0,Math.min(20000,Number(e.target.value)||0))})}/></Field><Field label="Seed"><input type="number" min="0" max="4294967295" value={config.seed} onChange={e=>patchConfig({seed:Math.max(0,Number(e.target.value)||0)})}/></Field></div></Card>
    {!comparison ? <Card><EmptyState icon={<BarChart3 size={27}/>} title="No comparison yet" description="Run a paired benchmark to get real results from the backend. No sample or placeholder statistics are shown." action={<Button onClick={onCompare} disabled={!!busy}><Play size={15} fill="currentColor"/> Run paired benchmark</Button>}/></Card> : <>
      <div className="trace-banner"><div className="trace-icon"><ShieldCheck size={18}/></div><div><strong>Fair comparison verified</strong><span>Both policies received the same {comparison.request_count.toLocaleString()} requests and initial disk state.</span><code>{comparison.trace_fingerprint}</code></div><StatusPill tone={comparison.same_trace_for_both_policies?'green':'red'}>{comparison.same_trace_for_both_policies?'Same trace':'Mismatch'}</StatusPill></div>
      <div className="comparison-grid"><PolicyScorecard policy="Standard LRU" subtitle="Reference policy" color="violet" result={lru}/><PolicyScorecard policy="Adaptive LRU" subtitle="Probationary + protected" color="cyan" result={adaptive}/></div>
      <div className="two-col-grid"><Card className="chart-card"><div className="card-heading"><div><h3>Metric comparison</h3><p>Lower is better for evictions and disk operations; higher for hit ratio.</p></div></div><div className="chart-area"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} barGap={5}><CartesianGrid stroke="#20283a" strokeDasharray="3 3" vertical={false}/><XAxis dataKey="metric" stroke="#69758b" tickLine={false} axisLine={false} tick={{fontSize:10}}/><YAxis stroke="#69758b" tickLine={false} axisLine={false} tick={{fontSize:10}}/><Tooltip contentStyle={tooltipStyle}/><Legend/><Bar dataKey="lru" name="Standard LRU" fill="#8b7cff" radius={[4,4,0,0]}/><Bar dataKey="adaptive" name="Adaptive LRU" fill="#43c8c2" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></div></Card><Card className="delta-card"><div className="card-heading"><div><h3>Outcome summary</h3><p>Observed difference in hit ratio</p></div></div><div className={`delta-value ${hitDelta>=0?'delta-positive':'delta-negative'}`}>{hitDelta>0?'+':''}{fmt(hitDelta,2)} <small>pp</small></div><p className="delta-copy">{hitDelta>0?'Adaptive LRU recorded a higher hit ratio on this trace.':hitDelta<0?'Standard LRU recorded a higher hit ratio on this trace.':'Both policies recorded the same hit ratio on this trace.'} Results depend on workload and capacity; neither policy is guaranteed to win.</p><div className="detail-list"><div><span>LRU hit ratio</span><strong>{pct(metric(lru?.metrics,'hit_ratio'))}</strong></div><div><span>Adaptive hit ratio</span><strong>{pct(metric(adaptive?.metrics,'hit_ratio'))}</strong></div><div><span>Actual LRU execution</span><strong>{shortTime(metric(lru?.metrics,'actual_execution_seconds'))}</strong></div><div><span>Actual Adaptive execution</span><strong>{shortTime(metric(adaptive?.metrics,'actual_execution_seconds'))}</strong></div></div></Card></div>
      <Card><div className="card-heading"><div><h3>Full metrics</h3><p>Directly returned by the simulation engine</p></div><span className="seed-display">Seed <strong>{comparison.seed}</strong></span></div><MetricsComparison lru={lru?.metrics} adaptive={adaptive?.metrics}/></Card>
    </>}
  </div>
}
function PolicyScorecard({policy,subtitle,color,result}:{policy:string;subtitle:string;color:'violet'|'cyan';result?: { metrics: MetricSet; policy_diagnostics: Record<string, number | string> } }) {
  return <Card className={`policy-scorecard score-${color}`}><div className="scorecard-top"><div className={`score-icon score-icon-${color}`}>{color==='violet'?<Layers3 size={19}/>:<ShieldCheck size={19}/>}</div><div><h3>{policy}</h3><p>{subtitle}</p></div><span className="scorecard-mark">{color==='violet'?'01':'02'}</span></div><div className="score-hit"><span>Read hit ratio</span><strong>{result?pct(metric(result.metrics,'hit_ratio')):'—'}</strong></div><div className="score-metrics"><div><span>Read hits</span><strong>{result?fmt(metric(result.metrics,'hits'),0):'—'}</strong></div><div><span>Read misses</span><strong>{result?fmt(metric(result.metrics,'misses'),0):'—'}</strong></div><div><span>Evictions</span><strong>{result?fmt(metric(result.metrics,'evictions'),0):'—'}</strong></div></div></Card>
}
function MetricsComparison({lru,adaptive}:{lru?:MetricSet;adaptive?:MetricSet}) {
  const keys:[string,string][]=[['requests','All requests'],['read_requests','Read requests'],['write_requests','Write requests'],['hits','Read hits'],['misses','Read misses'],['write_hits','Write hits'],['write_misses','Write misses'],['hit_ratio','Read hit ratio'],['admissions','Admissions'],['promotions','Promotions'],['evictions','Evictions'],['write_backs','Write-backs'],['disk_reads','Disk reads'],['disk_writes','Disk writes'],['capacity_utilization','Capacity utilization'],['actual_execution_seconds','Actual execution time'],['simulated_storage_seconds','Simulated storage time'],['simulated_cost','Simulated cost']]
  return <div className="metrics-table-wrap"><table className="metrics-table"><thead><tr><th>Metric</th><th>Standard LRU</th><th>Adaptive LRU</th><th>Δ Adaptive − LRU</th></tr></thead><tbody>{keys.map(([key,label])=>{const a=metric(lru,key),b=metric(adaptive,key);const isRatio=key.includes('ratio')||key.includes('utilization');const format=(v:number)=>isRatio?pct(v):key.includes('seconds')?shortTime(v):fmt(v,3);return <tr key={key}><td>{label}</td><td>{format(a)}</td><td>{format(b)}</td><td className={b>a?'delta-up':b<a?'delta-down':''}>{isRatio?`${(b-a>=0?'+':'')}${fmt((b-a)*100,2)} pp`:key.includes('seconds')?`${b-a>=0?'+':''}${shortTime(b-a)}`:`${b-a>=0?'+':''}${fmt(b-a,3)}`}</td></tr>})}</tbody></table></div>
}

function Results({state,events,busy,onExport,onNavigate}:{state:SimulationState|null;events:RequestOutcome[];busy:string|null;onExport:(f:'json'|'csv')=>void;onNavigate:(p:Page)=>void}) {
  return <div className="page-stack"><PageTitle eyebrow="DATA / RESULTS & EXPORT" title="Run results" subtitle="Inspect the current simulation summary and download the backend's raw output." action={<div className="export-actions"><Button variant="secondary" onClick={()=>onExport('csv')} disabled={!state||!!busy}><FileSpreadsheet size={15}/> Export CSV</Button><Button onClick={()=>onExport('json')} disabled={!state||!!busy}><FileJson size={15}/> Export JSON</Button></div>}/>
    {!state ? <Card><EmptyState icon={<FileSpreadsheet size={27}/>} title="No results available" description="Run a simulation first. Results and downloads are fetched from the FastAPI backend." action={<Button onClick={()=>onNavigate('simulator')}>Open simulator</Button>}/></Card> : <>
      <div className="results-summary"><div className="result-summary-main"><div className="eyebrow">SIMULATION SUMMARY</div><h2>{state.config.policy==='lru'?'Standard LRU':'Adaptive LRU'} <span>·</span> {state.config.workload.replaceAll('_',' ')}</h2><p>Simulation ID <code>{state.simulation_id}</code></p></div><StatusPill tone={state.done?'green':'blue'}>{state.done?'Completed':`${state.next_request_index}/${state.total_requests} processed`}</StatusPill></div>
      <div className="metrics-grid"><MetricCard label="Read hit ratio" value={pct(metric(state.metrics,'hit_ratio'))} detail={`${metric(state.metrics,'hits')} read hits`} icon={<Target size={18}/>} accent="green"/><MetricCard label="Read misses" value={fmt(metric(state.metrics,'misses'),0)} detail="Read misses from cache" icon={<Search size={18}/>} accent="orange"/><MetricCard label="Evictions" value={fmt(metric(state.metrics,'evictions'),0)} detail={`${metric(state.metrics,'write_backs')} write-backs`} icon={<ArrowDownRight size={18}/>} accent="cyan"/><MetricCard label="Capacity used" value={`${state.used_bytes} B`} detail={`${pct(state.capacity_utilization)} of configured capacity`} icon={<Layers3 size={18}/>} accent="violet"/></div>
      <div className="two-col-grid"><Card><div className="card-heading"><div><h3>Configuration</h3><p>Values submitted to the backend</p></div><Settings2 size={16} className="muted-icon"/></div><div className="detail-list result-config">{Object.entries({Policy:state.config.policy,Workload:state.config.workload.replaceAll('_',' '),'Cache capacity':`${state.config.capacity_bytes} bytes`,'Request count':state.config.request_count,Seed:state.config.seed,'File count':state.config.file_count,'Hot-set size':state.config.hot_set_size}).map(([k,v])=><div key={k}><span>{k}</span><strong>{v}</strong></div>)}</div></Card><Card><div className="card-heading"><div><h3>Runtime & modeled cost</h3><p>Kept separate by the Python engine</p></div><Clock3 size={16} className="muted-icon"/></div><div className="detail-list result-config"><div><span>Actual Python execution</span><strong>{shortTime(metric(state.metrics,'actual_execution_seconds'))}</strong></div><div><span>Simulated storage time</span><strong>{shortTime(metric(state.metrics,'simulated_storage_seconds'))}</strong></div><div><span>Simulated cost units</span><strong>{fmt(metric(state.metrics,'simulated_cost'),2)}</strong></div><div><span>Disk reads / writes</span><strong>{state.disk_reads} / {state.disk_writes}</strong></div></div><div className="info-note"><CircleHelp size={14}/> Simulated storage time is a model, not physical disk latency.</div></Card></div>
      <Card className="activity-card"><div className="card-heading"><div><h3>Request history</h3><p>{events.length} recorded outcomes · latest first</p></div><span className="result-history-tag">API data</span></div>{events.length ? <div className="event-list">{[...events].reverse().slice(0,100).map(e=><EventRow key={`${e.index}-${e.request.operation}`} event={e}/>)}</div> : <ChartEmpty text="Request history is empty. Step or run the simulation to record outcomes."/>}</Card>
    </>}
  </div>
}

export default App
