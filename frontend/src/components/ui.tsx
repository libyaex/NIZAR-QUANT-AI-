import type { ReactNode } from 'react';
import type { TradingState } from '../types';

export function Card({ title, action, children, className = '' }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && <div className="card-head"><h3>{title}</h3>{action}</div>}
      {children}
    </section>
  );
}
export function Stat({ label, value, sub, cls = '' }: { label: string; value: ReactNode; sub?: ReactNode; cls?: string }) {
  return <div className="card stat"><div className="label">{label}</div><div className={`value ${cls}`}>{value}</div>{sub && <div className="sub">{sub}</div>}</div>;
}
export const Pill = ({ tone = 'gray', children, dot }: { tone?: 'green' | 'red' | 'amber' | 'blue' | 'gray'; children: ReactNode; dot?: boolean }) => (
  <span className={`pill ${tone}`}>{dot && <span className="dot" />}{children}</span>
);
export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;
export const Banner = ({ kind = 'warn', children }: { kind?: 'warn' | 'err' | 'ok'; children: ReactNode }) => <div className={`banner ${kind}`}>{children}</div>;
export const Skeleton = ({ h = 80 }: { h?: number }) => <div className="skeleton" style={{ height: h }} />;

export function Seg<T extends string>({ value, options, onChange }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return <div className="seg">{options.map((o) => <button key={o.v} className={o.v === value ? 'on' : ''} onClick={() => onChange(o.v)}>{o.label}</button>)}</div>;
}
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <div className="field"><label>{label}</label>{children}{hint && <span className="hint">{hint}</span>}</div>;
}

const STATE: Record<TradingState, { tone: 'green' | 'red' | 'amber' | 'blue'; text: string }> = {
  engine_ready: { tone: 'blue', text: 'Engine Ready' },
  trading_active: { tone: 'green', text: 'Trading Active' },
  trading_stopped: { tone: 'amber', text: 'Trading Stopped' },
  connection_lost: { tone: 'red', text: 'Connection Lost' },
  emergency_halt: { tone: 'red', text: 'Emergency Halt' },
};
export const StateBadge = ({ state }: { state: TradingState }) => <Pill tone={STATE[state].tone} dot>{STATE[state].text}</Pill>;
export const ModePill = ({ mode }: { mode: string }) => <Pill tone={mode === 'live' ? 'red' : 'blue'}>{mode === 'live' ? 'LIVE' : 'PAPER'}</Pill>;
export const DecisionPill = ({ d }: { d: string }) => <Pill tone={d === 'LONG' ? 'green' : d === 'SHORT' ? 'red' : 'gray'}>{d}</Pill>;

export function Ring({ pct, size = 150, stroke = 12, label, sub }: { pct: number; size?: number; stroke?: number; label: string; sub?: string }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, off = c * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return (
    <div className="ring-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={off} style={{ transition: 'stroke-dashoffset .8s' }} />
      </svg>
      <div className="center"><b>{label}</b>{sub && <div className="tiny muted">{sub}</div>}</div>
    </div>
  );
}

/** Equity curve (cumulative realized P&L). */
export function LineArea({ points, height = 180 }: { points: number[]; height?: number }) {
  if (points.length < 2) return <Empty>Not enough closed trades yet</Empty>;
  const w = 600, pad = 8, min = Math.min(0, ...points), max = Math.max(0, ...points), span = max - min || 1;
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - pad * 2);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2);
  const d = points.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const up = points[points.length - 1] >= 0, col = up ? 'var(--long)' : 'var(--short)';
  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <line x1={0} x2={w} y1={y(0)} y2={y(0)} stroke="var(--line)" strokeDasharray="4 4" />
      <path d={`${d} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill={col} opacity=".1" />
      <path d={d} fill="none" stroke={col} strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
export function Bars({ items, height = 140 }: { items: { label: string; value: number }[]; height?: number }) {
  if (!items.length) return <Empty>No data yet</Empty>;
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1e-9);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, height }}>
      {items.map((i) => (
        <div key={i.label} title={`${i.label}: ${i.value}`} style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ height: '50%', display: 'flex', alignItems: 'flex-end' }}>{i.value > 0 && <div style={{ width: '100%', height: `${(i.value / max) * 100}%`, background: 'var(--long)', borderRadius: 3 }} />}</div>
          <div style={{ height: '50%' }}>{i.value < 0 && <div style={{ width: '100%', height: `${(-i.value / max) * 100}%`, background: 'var(--short)', borderRadius: 3 }} />}</div>
        </div>
      ))}
    </div>
  );
}
