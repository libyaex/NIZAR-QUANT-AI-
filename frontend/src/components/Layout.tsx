import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { supabase, apiFetch } from '../lib/api';
import type { EngineStatus, TradingState } from '../types';

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/scanner', label: 'Market Scanner' },
  { to: '/analysis', label: 'Analysis' },
  { to: '/trading', label: 'Trading Controls' },
  { to: '/positions', label: 'Positions' },
  { to: '/history', label: 'Trade History' },
  { to: '/performance', label: 'Performance' },
  { to: '/missions', label: 'Profit Mission' },
  { to: '/exchanges', label: 'Exchanges' },
  { to: '/settings', label: 'Settings' },
];

export function StateBadge({ state }: { state: TradingState }) {
  const map: Record<TradingState, { cls: string; text: string }> = {
    engine_ready: { cls: 'amber', text: 'Engine Ready' },
    trading_active: { cls: 'green', text: 'Trading Active' },
    trading_stopped: { cls: 'amber', text: 'Trading Stopped' },
    connection_lost: { cls: 'red', text: 'Connection Lost' },
    emergency_halt: { cls: 'red', text: 'Emergency Halt' },
  };
  const m = map[state];
  return (
    <span className={`status-badge ${m.cls}`}>
      <span className="dot" />
      {m.text}
    </span>
  );
}

export function useEngineStatus(intervalMs = 5000) {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const s = await apiFetch<EngineStatus>('/api/status');
        if (alive) setStatus(s);
      } catch {
        if (alive) setStatus(null);
      }
    };
    load();
    const id = setInterval(load, intervalMs);
    return () => { alive = false; clearInterval(id); };
  }, [intervalMs]);
  return status;
}

export default function Layout() {
  const navigate = useNavigate();
  const status = useEngineStatus(8000);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) navigate('/auth');
    });
  }, [navigate]);

  const signOut = async () => {
    await supabase.auth.signOut();
    navigate('/auth');
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">NIZAR <span>QUANT AI</span></div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            {n.label}
          </NavLink>
        ))}
        <button className="nav-link" onClick={signOut} style={{ marginTop: 'auto' }}>Sign Out</button>
      </aside>
      <main className="main">
        <Outlet context={{ status }} />
      </main>
    </div>
  );
}
