import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { Mission } from '../types';

const PRESETS = [
  { from: 1, to: 20 },
  { from: 1, to: 100 },
  { from: 5, to: 50 },
  { from: 10, to: 100 },
  { from: 50, to: 500 },
  { from: 100, to: 1000 },
];

export default function Missions() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [compounding, setCompounding] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    try { setMissions((await apiFetch<{ missions: Mission[] }>('/api/missions')).missions); } catch { /* noop */ }
  };

  useEffect(() => { load(); }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await apiFetch('/api/missions', {
        method: 'POST',
        body: JSON.stringify({ startingCapital: Number(from), targetCapital: Number(to), compounding }),
      });
      setFrom(''); setTo('');
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const update = async (id: string, status: string) => {
    await apiFetch('/api/missions/' + id, { method: 'PUT', body: JSON.stringify({ status }) });
    await load();
  };

  const active = missions.find((m) => m.status === 'active');
  const fmt = (n: number) => '$' + n.toFixed(2);
  const cls = (n: number) => (n >= 0 ? 'pos' : 'neg');

  return (
    <div>
      <h1 className="page-title">Profit Mission</h1>

      {active && (
        <div className="mission-hero" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <h3 style={{ margin: 0 }}>Active Mission</h3>
            <button className="btn small" onClick={() => update(active.id, 'paused')}>Pause</button>
          </div>
          <div className="amounts">
            <div><div className="stat-value">{fmt(active.currentCapital)}</div><div className="stat-label">Current</div></div>
            <div><div className="stat-value">{fmt(active.targetCapital)}</div><div className="stat-label">Target</div></div>
            <div><div className={`stat-value ${cls(active.realizedProfit)}`}>{fmt(active.realizedProfit)}</div><div className="stat-label">Realized</div></div>
            <div><div className={`stat-value ${cls(active.unrealizedProfit)}`}>{fmt(active.unrealizedProfit)}</div><div className="stat-label">Unrealized</div></div>
            <div><div className="stat-value">{fmt(active.remaining)}</div><div className="stat-label">Remaining</div></div>
          </div>
          <div className="progress-wrap"><div className="progress-bar" style={{ width: active.progressPct + '%' }} /></div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-dim)' }}>
            <span>{active.progressPct.toFixed(1)}% complete</span>
            <span>Compounding: {active.compounding ? 'ON' : 'OFF'}</span>
          </div>
        </div>
      )}

      <div className="grid cols-2">
        <div className="card">
          <h3>New Mission</h3>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
            {PRESETS.map((p) => (
              <button key={p.from + '-' + p.to} className="btn small"
                onClick={() => { setFrom(String(p.from)); setTo(String(p.to)); }}>
                ${p.from} → ${p.to}
              </button>
            ))}
          </div>
          <form onSubmit={create}>
            <div className="form-row">
              <label>Starting Capital (USD)</label>
              <input type="number" min="1" step="any" value={from} onChange={(e) => setFrom(e.target.value)} required />
            </div>
            <div className="form-row">
              <label>Target Capital (USD)</label>
              <input type="number" min="1" step="any" value={to} onChange={(e) => setTo(e.target.value)} required />
            </div>
            <div className="form-row">
              <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="checkbox" style={{ width: 'auto' }} checked={compounding} onChange={(e) => setCompounding(e.target.checked)} />
                Automatic profit compounding
              </label>
            </div>
            {error && <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>}
            <button className="btn primary" disabled={busy}>Start Mission</button>
            <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 10 }}>
              Targets are personal goals, not guaranteed results. Position sizing always obeys risk limits.
            </p>
          </form>
        </div>

        <div className="card">
          <h3>All Missions</h3>
          {missions.length === 0 ? <p className="empty">No missions yet.</p> : (
            <table>
              <thead><tr><th>From → To</th><th>Progress</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {missions.map((m) => (
                  <tr key={m.id}>
                    <td>{fmt(m.startingCapital)} → {fmt(m.targetCapital)}</td>
                    <td>{m.progressPct.toFixed(1)}%</td>
                    <td>{m.status}</td>
                    <td>
                      {m.status === 'paused' && <button className="btn small" onClick={() => update(m.id, 'active')}>Resume</button>}
                      {m.status === 'active' && <button className="btn small" onClick={() => update(m.id, 'paused')}>Pause</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
