import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { getSupabase, missingEnvVars, apiBasePath, apiFetch } from '../lib/api';
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

/** Visible setup banner shown instead of a blank page when the frontend
 *  environment (Vite VITE_* variables) is not configured on Vercel. */
export function SetupBanner() {
  const missing = missingEnvVars();
  const noApi = !apiBasePath();
  if (missing.length === 0 && !noApi) return null;
  return (
    <div className="card" style={{ marginBottom: 16, borderColor: 'var(--red)' }}>
      <h3 style={{ color: 'var(--red)' }}>Configuration Required</h3>
      <p style={{ fontSize: 14, lineHeight: 1.6 }}>
        This deployment is missing frontend environment variables. Add them in
        Vercel → Project → Settings → Environment Variables, then redeploy:
      </p>
      <ul style={{ paddingLeft: 20, fontSize: 13, lineHeight: 1.8, color: 'var(--text-dim)' }}>
        {missing.map((v) => (
          <li key={v}><code>{v}</code></li>
        ))}
        {noApi && <li><code>VITE_API_URL</code></li>}
      </ul>
      <p style={{ fontSize: 12, color: 'var(--text-dim)' }}>
        Values: Supabase project URL and anon key, plus your Railway backend URL.
      </p>
    </div>
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
    const client = getSupabase();
    if (!client) return; // SetupBanner explains configuration instead
    client.auth.getSession().then(({ data }) => {
      if (!data.session) navigate('/auth');
    });
  }, [navigate]);

  const signOut = async () => {
    const client = getSupabase();
    if (client) await client.auth.signOut();
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
        <SetupBanner />
        <Outlet context={{ status }} />
      </main>
    </div>
  );
}
