import { useState } from 'react';
import { Link } from 'react-router-dom';
import { post, usePoll, useSession } from '../lib/api';
import type { Dashboard as Dash, FeedStatus, Opportunity } from '../types';
import { Banner, Card, ModePill, Ring, Skeleton, Stat, StateBadge } from '../components/ui';
import { FeedStrip, OpportunityList, PositionList, SignInCta } from '../components/shared';
import { money, signed, tone } from '../lib/format';

export default function Dashboard() {
  const { session } = useSession();
  const dash = usePoll<Dash>(session ? '/api/dashboard' : null, 4000);
  const market = usePoll<{ exchanges: FeedStatus[]; opportunities: Opportunity[]; scanned: number }>('/api/market?limit=5', 5000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const d = dash.data;
  const active = d?.status.tradingActive ?? false;
  const control = async (action: 'start' | 'stop') => {
    setBusy(true); setErr('');
    try { await post('/api/trading/ctl', { action }); await dash.reload(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const closeAll = async () => {
    if (!confirm('Close ALL open positions at market price?')) return;
    setBusy(true);
    try { await post('/api/trading/close-all'); await dash.reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const m = d?.mission;
  const opps = d?.opportunities ?? market.data?.opportunities ?? [];

  return (
    <div className="page">
      {!session && <SignInCta />}
      {err && <Banner kind="err">{err}</Banner>}
      {d?.status.haltReason && <Banner kind="warn"><div><b>Risk protection active:</b> {d.status.haltReason.replace(/_/g, ' ')}. New trades are blocked. <Link to="/trading" style={{ textDecoration: 'underline' }}>Review</Link></div></Banner>}

      {session && (
        <Card className="hero">
          <div className="row" style={{ marginBottom: 6 }}>
            <span className="muted small">Account balance</span>
            {d && <span style={{ display: 'flex', gap: 6 }}><ModePill mode={d.status.mode} /><StateBadge state={d.status.state} /></span>}
          </div>
          {d ? (
            <>
              <div className="big">{money(d.status.equity)}</div>
              <div className="row small" style={{ marginTop: 6, justifyContent: 'flex-start', gap: 18, flexWrap: 'wrap' }}>
                <span className={tone(d.today.pnl)}>Today {signed(d.today.pnl)}</span>
                <span className={`${tone(d.unrealized)}`}>Open P&L {signed(d.unrealized)}</span>
                <span className="muted">{d.today.trades} trades today</span>
              </div>
              <div className="grid g2" style={{ marginTop: 16, gap: 10 }}>
                <button className="btn primary go" disabled={busy || active} onClick={() => control('start')}>{active ? 'TRADING ACTIVE' : 'START TRADING'}</button>
                <button className="btn danger go" disabled={busy || !active} onClick={() => control('stop')}>STOP TRADING</button>
              </div>
              <div className="row" style={{ marginTop: 10 }}>
                <span className="tiny muted">Stop only blocks new entries; open trades keep their stop-loss / take-profit.</span>
                <button className="btn sm ghost" disabled={busy || d.positions.length === 0} onClick={closeAll}>Close all</button>
              </div>
            </>
          ) : <Skeleton h={150} />}
        </Card>
      )}

      <Link to="/missions">
        <Card className="hero" title="Profit Mission" action={<span className="small pos">{m ? m.status : 'Start one'} ›</span>}>
          {m ? (
            <div className="row" style={{ gap: 18 }}>
              <Ring pct={m.progressPct} size={118} stroke={11} label={`${m.progressPct.toFixed(0)}%`} />
              <div style={{ flex: 1 }}>
                <div className="stat"><div className="label">Current → Target</div><div className="value" style={{ fontSize: 20 }}>{money(m.currentCapital)} → {money(m.targetCapital)}</div></div>
                <div className="small muted" style={{ marginTop: 6 }}>Realized <b className={tone(m.realizedProfit)}>{signed(m.realizedProfit)}</b> · Unrealized <span className={tone(m.unrealizedProfit)}>{signed(m.unrealizedProfit)}</span></div>
                <div className="small muted">{money(m.remaining)} to go</div>
              </div>
            </div>
          ) : <div className="muted small">Set a capital-growth goal (for example $10 → $100) and let the bot work toward it with strict risk limits.</div>}
        </Card>
      </Link>

      <div className="grid g2">
        <Card title="Best opportunities" action={<Link to="/scanner" className="small muted">All ›</Link>}>
          <OpportunityList items={opps} empty={market.error ? 'Backend unreachable' : 'No qualifying setups right now — the scanner keeps looking.'} />
        </Card>
        <Card title="Active positions" action={<Link to="/positions" className="small muted">Details ›</Link>}>
          {session ? <PositionList items={d?.positions ?? []} /> : <div className="empty">Sign in to see positions</div>}
        </Card>
      </div>

      {d && (
        <div className="grid g4">
          <Stat label="Win rate" value={`${d.performance.winRate.toFixed(0)}%`} sub={`${d.performance.totalTrades} trades`} />
          <Stat label="Net P&L" value={signed(d.performance.netPnl)} cls={tone(d.performance.netPnl)} sub="realized" />
          <Stat label="Profit factor" value={d.performance.profitFactor.toFixed(2)} sub="gross win / loss" />
          <Stat label="Max drawdown" value={money(d.performance.maxDrawdown)} sub="from peak" />
        </div>
      )}

      <Card title="Market engine" action={<span className="tiny muted">{market.data?.scanned ?? 0} markets analysed</span>}>
        {market.data ? <FeedStrip feeds={market.data.exchanges} /> : <Skeleton h={30} />}
      </Card>
    </div>
  );
}
