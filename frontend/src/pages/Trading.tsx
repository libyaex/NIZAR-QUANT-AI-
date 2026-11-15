import { useState } from 'react';
import { post, put, usePoll, useSession } from '../lib/api';
import type { Dashboard, RiskSettings } from '../types';
import { Banner, Card, ModePill, Pill, Skeleton, StateBadge } from '../components/ui';
import { FeedStrip, SignInCta } from '../components/shared';
import { duration, money } from '../lib/format';

export default function Trading() {
  const { session } = useSession();
  const dash = usePoll<Dashboard>(session ? '/api/dashboard' : null, 4000);
  const risk = usePoll<RiskSettings>(session ? '/api/settings/risk' : null, 30000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'err' | 'ok'; text: string } | null>(null);
  if (!session) return <div className="page"><SignInCta /></div>;

  const d = dash.data, s = risk.data;
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); await dash.reload(); await risk.reload(); if (ok) setMsg({ kind: 'ok', text: ok }); }
    catch (e) { setMsg({ kind: 'err', text: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const switchMode = (mode: 'paper' | 'live') => {
    if (!s || s.tradingMode === mode) return;
    if (mode === 'live' && !confirm('Switch to LIVE trading? The bot will use REAL money on your connected exchange when you press START.')) return;
    run(() => put('/api/settings/risk', { ...s, tradingMode: mode }), `Mode switched to ${mode.toUpperCase()}. Trading was stopped for safety.`);
  };

  return (
    <div className="page">
      <div className="page-head"><div><h1>Automated Trading</h1><p>Backend-controlled state — the browser can close without affecting it.</p></div></div>
      {msg && <Banner kind={msg.kind}>{msg.text}</Banner>}
      {d?.status.message && <Banner kind="warn">{d.status.message}</Banner>}
      {!d ? <Skeleton h={220} /> : (
        <>
          <Card className="hero">
            <div className="row"><StateBadge state={d.status.state} /><ModePill mode={d.status.mode} /></div>
            <div className="grid g3" style={{ margin: '16px 0 4px' }}>
              <div className="stat"><div className="label">Balance</div><div className="value">{money(d.status.equity)}</div></div>
              <div className="stat"><div className="label">Open positions</div><div className="value">{d.status.openPositions}</div></div>
              <div className="stat"><div className="label">Engine uptime</div><div className="value">{duration(d.status.uptimeSeconds)}</div></div>
            </div>
            <div className="grid g2" style={{ marginTop: 14, gap: 10 }}>
              <button className="btn primary go" disabled={busy || d.status.tradingActive} onClick={() => run(() => post('/api/trading/ctl', { action: 'start' }))}>START TRADING</button>
              <button className="btn danger go" disabled={busy || !d.status.tradingActive} onClick={() => run(() => post('/api/trading/ctl', { action: 'stop' }))}>STOP TRADING</button>
            </div>
            <div className="grid g2" style={{ marginTop: 10, gap: 10 }}>
              <button className="btn block" disabled={busy || d.positions.length === 0}
                onClick={() => confirm('Close ALL open positions at market price?') && run(() => post('/api/trading/close-all'), 'Close-all submitted')}>CLOSE ALL POSITIONS</button>
              <button className="btn danger block" disabled={busy}
                onClick={() => confirm('Emergency halt blocks all new trades until you reset risk. Continue?') && run(() => post('/api/trading/ctl', { action: 'halt' }))}>EMERGENCY HALT</button>
            </div>
            <p className="tiny muted" style={{ marginTop: 10 }}>STOP blocks new entries only. Existing positions stay managed with their stop-loss, take-profit and trailing rules.</p>
          </Card>

          {d.status.haltReason && (
            <Banner kind="warn"><div style={{ flex: 1 }}><b>Risk halt: {d.status.haltReason.replace(/_/g, ' ')}.</b> Daily-loss halts clear on the next UTC day. You can also reset manually.</div>
              <button className="btn sm" disabled={busy} onClick={() => run(() => post('/api/risk/reset'), 'Risk state reset')}>Reset risk</button></Banner>
          )}

          <div className="grid g2">
            <Card title="Execution mode">
              <div className="stack">
                <div className="seg" style={{ alignSelf: 'flex-start' }}>
                  <button className={s?.tradingMode === 'paper' ? 'on' : ''} onClick={() => switchMode('paper')}>Paper</button>
                  <button className={s?.tradingMode === 'live' ? 'on' : ''} onClick={() => switchMode('live')}>Live</button>
                </div>
                <p className="small muted">
                  <b>Paper</b>: real market prices and order books, simulated account ({money(s?.paperBalance)}). Use it to verify the bot's behaviour risk-free.<br />
                  <b>Live</b>: signed orders on your connected exchange with real funds. Requires API keys (trade permission, withdrawals off).
                </p>
                {s?.tradingMode === 'paper' && <button className="btn sm" disabled={busy || d.positions.length > 0} onClick={() => run(() => post('/api/paper/reset'), 'Paper account reset')}>Reset paper account</button>}
              </div>
            </Card>
            <Card title="Market engine">
              <FeedStrip feeds={d.exchanges} />
              <div className="stack small" style={{ marginTop: 12 }}>
                {d.exchanges.map((f) => (
                  <div key={f.id} className="row"><span>{f.id.toUpperCase()}</span>
                    <span className="muted">{f.status === 'ok' ? `${f.signals} signals · ws ${f.ws.connected ? 'live' : 'off'}` : <Pill tone="red">{f.error.slice(0, 40) || 'starting'}</Pill>}</span></div>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
