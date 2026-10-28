import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, LoaderCircle, WifiOff } from 'lucide-react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{children}</section>
}
export function SectionHeading({ eyebrow, title, description, action }: {
  eyebrow?: string; title: string; description?: string; action?: ReactNode
}) {
  return <div className="section-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2>{description && <p>{description}</p>}</div>{action && <div className="heading-action">{action}</div>}</div>
}
export function Button({ children, onClick, variant = 'primary', disabled, type = 'button', className = '' }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; disabled?: boolean; type?: 'button' | 'submit'; className?: string
}) {
  return <button type={type} onClick={onClick} disabled={disabled} className={`button button-${variant} ${className}`}>{children}</button>
}
export function StatusPill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue' }) {
  return <span className={`status-pill status-${tone}`}><span className="status-dot" />{children}</span>
}
export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{description}</p>{action}</div>
}
export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return <div className="error-banner" role="alert"><AlertCircle size={18}/><span>{message}</span>{onDismiss && <button className="inline-dismiss" onClick={onDismiss} aria-label="Dismiss error">×</button>}</div>
}
export function Loading({ label = 'Loading' }: { label?: string }) {
  return <span className="loading-inline"><LoaderCircle size={16} className="spin"/>{label}</span>
}
export function HealthNotice({ online, version }: { online: boolean; version?: string }) {
  return <div className={`health-notice ${online ? 'online' : 'offline'}`}>{online ? <CheckCircle2 size={14}/> : <WifiOff size={14}/>}<span>{online ? `API connected${version ? ` · v${version}` : ''}` : 'API disconnected'}</span></div>
}
export function MetricCard({ label, value, detail, icon, accent = 'violet' }: {
  label: string; value: string; detail?: string; icon: ReactNode; accent?: 'violet' | 'cyan' | 'green' | 'orange'
}) {
  return <Card className="metric-card"><div className={`metric-icon accent-${accent}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div>{detail && <div className="metric-detail">{detail}</div>}</Card>
}
