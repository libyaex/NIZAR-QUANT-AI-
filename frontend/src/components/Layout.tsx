import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { configIssues, getSupabase, usePoll, useSession } from '../lib/api';
import type { EngineStatus, FeedStatus } from '../types';
import { Banner, ModePill, Pill, StateBadge } from './ui';
import { Icons } from './icons';

const PRIMARY = [
  { to: '/', label: 'Home', icon: Icons.home },
  { to: '/scanner', label: 'Scanner', icon: Icons.scan },
  { to: '/trading', label: 'Trade', icon: Icons.bolt },
  { to: '/missions', label: 'Mission', icon: Icons.target },
];
const MORE = [
  { to: '/analysis', label: 'Analysis & Chart', icon: Icons.chart },
  { to: '/positions', label: 'Active Positions', icon: Icons.list },
  { to: '/history', label: 'Trade History', icon: Icons.clock },
  { to: '/performance', label: 'Performance', icon: Icons.stats },
  { to: '/exchanges', label: 'Exchanges', icon: Icons.link },
  { to: '/settings', label: 'Risk & Settings', icon: Icons.gear },
];
const ALL = [PRIMARY[0], PRIMARY[1], MORE[0], PRIMARY[2], MORE[1], MORE[2], MORE[3], PRIMARY[3], MORE[4], MORE[5]];

export default function Layout() {
  const nav = useNavigate();
  const loc = useLocation();
  const { session } = useSession();
  const [sheet, setSheet] = useState(false);
  const status = usePoll<EngineStatus>(session ? '/api/status' : null, 5000);
  const market = usePoll<{ exchanges: FeedStatus[] }>('/api/market?limit=1', 8000);
  const issues = configIssues();
  const feedsOk = (market.data?.exchanges ?? []).some((e) => e.status === 'ok');

  useEffect(() => setSheet(false), [loc.pathname]);

  const signOut = async () => { await getSupabase()?.auth.signOut(); nav('/auth'); };

  const badge = status.data
    ? <span style={{ display: 'flex', gap: 6 }}><ModePill mode={status.data.mode} /><StateBadge state={status.data.state} /></span>
    : market.error ? <Pill tone="red" dot>Backend offline</Pill>
    : market.data ? <Pill tone={feedsOk ? 'green' : 'red'} dot>{feedsOk ? 'Market live' : 'No market data'}</Pill>
    : <Pill dot>Connecting…</Pill>;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><i>N</i>NIZAR <span>QUANT AI</span></div>
        {ALL.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => `side-link${isActive ? ' active' : ''}`}>{n.icon}{n.label}</NavLink>
        ))}
        <div style={{ flex: 1 }} />
        {session
          ? <button className="side-link" onClick={signOut}>{Icons.logout}Sign out</button>
          : <NavLink to="/auth" className="side-link">{Icons.logout}Sign in</NavLink>}
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="brand"><i>N</i>NIZAR <span>QUANT AI</span></div>
          {badge}
        </header>
        <div className="page" style={{ paddingBottom: 0 }}>
          {issues.length > 0 && (
            <Banner kind="err"><div><b>Missing configuration:</b> {issues.join(', ')}. Add them in Vercel → Settings → Environment Variables, then redeploy.</div></Banner>
          )}
          {market.error && issues.length === 0 && <Banner kind="err"><div>{market.error.message}</div></Banner>}
        </div>
        <Outlet />
      </div>

      <nav className="tabbar">
        {PRIMARY.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => `tab${isActive ? ' active' : ''}`} style={{ textDecoration: 'none' }}>{n.icon}{n.label}</NavLink>
        ))}
        <button className={`tab${MORE.some((m) => m.to === loc.pathname) ? ' active' : ''}`} onClick={() => setSheet(true)}>{Icons.more}More</button>
      </nav>
      {sheet && (
        <>
          <div className="sheet-back" onClick={() => setSheet(false)} />
          <div className="sheet">
            {MORE.map((m) => <NavLink key={m.to} to={m.to} className={({ isActive }) => (isActive ? 'active' : '')}>{m.icon}{m.label}</NavLink>)}
            {session ? <a onClick={signOut}>{Icons.logout}Sign out</a> : <NavLink to="/auth">{Icons.logout}Sign in</NavLink>}
          </div>
        </>
      )}
    </div>
  );
}
