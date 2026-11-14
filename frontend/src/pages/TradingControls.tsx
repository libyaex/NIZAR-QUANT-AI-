import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { apiFetch } from '../lib/api';
import { StateBadge, useEngineStatus } from '../components/Layout';
import type { EngineStatus } from '../types';

type Ctx = { status: EngineStatus | null };

export default function TradingControls() {
  const ctx = useOutletContext<Ctx>();
  const live = useEngineStatus(5000);
  const status: EngineStatus | null = live ?? ctx.status;
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const control = async (action: 'start' | 'stop' | 'halt') => {
    if (action === 'halt' && !window.confirm('Activate EMERGENCY HALT? No new trades will open and risk limits lock.')) return;
    setBusy(true);
    setMsg('');
    try {
      const s = await apiFetch<EngineStatus>('/api/trading/ctl', { method: 'POST', body: JSON.stringify({ action }) });
      setMsg('Applied: ' + s.state);
    } catch (e) {
      setMsg('Error: ' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const closeAll = async () => {
    if (!window.confirm('Close ALL open positions immediately?')) return;
    setBusy(true);
    try {
      const r = await apiFetch<{ closed: number }>('/api/trading/close-all', { method: 'POST' });
      setMsg('Closed positions: ' + r.closed);
    } catch (e) {
      setMsg('Error: ' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">Automated Trading Controls</h1>
      <div className="grid cols-2">
        <div className="card">
          <h3>Engine State</h3>
          {status ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <StateBadge state={status.state} />
              <div className="stat-label">Uptime: {Math.floor(status.uptimeSeconds / 60)} min</div>
              <div className="stat-label">Connected exchanges: {status.exchangesConnected.join(', ') || 'none'}</div>
              <div className="stat-label">Open positions: {status.openPositions}</div>
            </div>
          ) : <p className="empty">Engine connection lost.</p>}
        </div>
        <div className="card">
          <h3>Controls</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <button className="btn start" disabled={busy} onClick={() => control('start')}>START TRADING</button>
            <button className="btn stop" disabled={busy} onClick={() => control('stop')}>STOP TRADING</button>
            <button className="btn danger" disabled={busy} onClick={closeAll}>CLOSE ALL POSITIONS</button>
            <button className="btn" disabled={busy} onClick={() => control('halt')}>EMERGENCY HALT</button>
          </div>
          {msg && <p style={{ marginTop: 12, fontSize: 13, color: 'var(--text-dim)' }}>{msg}</p>}
          <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 12 }}>
            STOP keeps managing existing positions with their protective SL/TP rules. The background market engine never shuts down.
          </p>
        </div>
      </div>
    </div>
  );
}
