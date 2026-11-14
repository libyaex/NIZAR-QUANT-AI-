import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { apiFetch } from '../lib/api';
import { StateBadge } from '../components/Layout';
import type { EngineStatus, Mission, Performance, Position } from '../types';

type Ctx = { status: EngineStatus | null };

export default function Dashboard() {
  const { status } = useOutletContext<Ctx>();
  const [positions, setPositions] = useState<Position[]>([]);
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [mission, setMission] = useState<Mission | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [p, perf, missions] = await Promise.all([
        apiFetch<Position[]>('/api/positions'),
        apiFetch<Performance>('/api/performance'),
        apiFetch<{ missions: Mission[] }>('/api/missions'),
      ]);
      setPositions(p);
      setPerformance(perf);
      setMission(missions.missions.find((m) => m.status === 'active') ?? missions.missions[0] ?? null);
    } catch {
      /* engine may not be ready */
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  const control = async (action: 'start' | 'stop') => {
    setBusy(true);
    try {
      await apiFetch('/api/trading/ctl', { method: 'POST', body: JSON.stringify({ action }) });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const fmt = (n: number) => n.toFixed(2);
  const pnlCls = (n: number) => (n >= 0 ? 'pos' : 'neg');

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 20 }}>
        <h1 className="page-title" style={{ marginBottom: 0 }}>Dashboard</h1>
        {status && <StateBadge state={status.state} />}
      </div>
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="card"><h3>Today P&L</h3>
          <div className={`stat-value ${pnlCls(performance?.todayPnl ?? 0)}`}>${fmt(performance?.todayPnl ?? 0)}</div>
          <div className="stat-label">Realized today</div></div>
        <div className="card"><h3>Open Positions</h3>
          <div className="stat-value">{positions.length}</div>
          <div className="stat-label">Managed automatically</div></div>
        <div className="card"><h3>Win Rate</h3>
          <div className="stat-value">{performance ? fmt(performance.winRate) : '—'}%</div>
          <div className="stat-label">{performance ? performance.totalTrades + ' trades' : 'No trades yet'}</div></div>
        <div className="card"><h3>Exchanges</h3>
          <div className="stat-value">{status ? status.exchangesConnected.length : 0}</div>
          <div className="stat-label">{status ? status.exchangesConnected.join(', ') : 'None connected'}</div></div>
      </div>
      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Automated Trading</h3>
          <p style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 14 }}>The background engine monitors markets continuously. Pressing START activates real order execution.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn start" disabled={busy || (status ? status.tradingActive : false)} onClick={() => control('start')}>START TRADING</button>
            <button className="btn stop" disabled={busy || !(status && status.tradingActive)} onClick={() => control('stop')}>STOP TRADING</button>
            <button className="btn danger" disabled={busy || positions.length === 0}
              onClick={() => apiFetch('/api/trading/close-all', { method: 'POST' }).then(load)}>CLOSE ALL POSITIONS</button>
          </div>
        </div>
        <div className="mission-hero">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>Profit Mission</h3>
            <Link to="/missions" className="btn small">Manage</Link>
          </div>
          {mission ? (
            <div>
              <div className="amounts">
                <div><div className="stat-value">${fmt(mission.currentCapital)}</div><div className="stat-label">Current</div></div>
                <div><div className="stat-value">${fmt(mission.targetCapital)}</div><div className="stat-label">Target</div></div>
                <div><div className={`stat-value ${pnlCls(mission.realizedProfit)}`}>${fmt(mission.realizedProfit)}</div><div className="stat-label">Realized P&L</div></div>
              </div>
              <div className="progress-wrap"><div className="progress-bar" style={{ width: mission.progressPct + '%' }} /></div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{fmt(mission.progressPct)}% complete</div>
            </div>
          ) : (
            <p className="empty">No mission yet — <Link to="/missions">create one</Link> to start a capital-growth challenge.</p>
          )}
        </div>
      </div>
      <div className="card">
        <h3>Active Positions</h3>
        {positions.length === 0 ? <p className="empty">No open positions.</p> : (
          <table>
            <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Mark</th><th>Unrealized</th><th>SL / TP</th></tr></thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.positionId}>
                  <td>{p.symbol}</td>
                  <td className={p.side === 'long' ? 'pos' : 'neg'}>{p.side.toUpperCase()}</td>
                  <td>{p.qty}</td><td>{p.entryPrice}</td><td>{p.markPrice}</td>
                  <td className={pnlCls(p.unrealizedPnl)}>${fmt(p.unrealizedPnl)}</td>
                  <td>{p.stopLoss} / {p.takeProfit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
