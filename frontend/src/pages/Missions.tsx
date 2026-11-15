import { useState } from 'react';
import { put, post, usePoll, useSession } from '../lib/api';
import type { Mission } from '../types';
import { Banner, Card, Field, Pill, Ring, Skeleton } from '../components/ui';
import { SignInCta } from '../components/shared';
import { money, signed, tone, when } from '../lib/format';

const PRESETS: [number, number][] = [[1, 20], [1, 100], [5, 50], [10, 100], [50, 500], [100, 1000]];

export default function Missions() {
  const { session } = useSession();
  const { data, reload } = usePoll<{ missions: Mission[] }>(session ? '/api/missions' : null, 6000);
  const [start, setStart] = useState('10');
  const [target, setTarget] = useState('100');
  const [compound, setCompound] = useState(true);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  if (!session) return <div className="page"><SignInCta /></div>;

  const [current, ...history] = data?.missions ?? [];
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(''); try { await fn(); await reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); } };
  const create = () => run(() => post('/api/missions', { startingCapital: Number(start), targetCapital: Number(target), compounding: compound }));
  const mult = Number(start) > 0 ? Number(target) / Number(start) : 0;

  return (
    <div className="page">
      <div className="page-head"><div><h1>Profit Mission</h1><p>A personal capital-growth goal. Examples only — results are never guaranteed.</p></div></div>
      {err && <Banner kind="err">{err}</Banner>}
      {!data ? <Skeleton h={240} /> : current && (
        <Card className="hero">
          {current.status === 'completed' && <Banner kind="ok"><div><b>Mission completed.</b> Target reached on {when(current.completedAt)}. New trades are paused — start a new mission below.</div></Banner>}
          <div className="row" style={{ gap: 20, flexWrap: 'wrap', marginTop: current.status === 'completed' ? 12 : 0 }}>
            <Ring pct={current.progressPct} size={170} stroke={14} label={`${current.progressPct.toFixed(1)}%`} sub="complete" />
            <div style={{ flex: 1, minWidth: 220 }} className="stack">
              <div className="row"><span className="muted small">Status</span><Pill tone={current.status === 'active' ? 'green' : current.status === 'paused' ? 'amber' : 'blue'} dot>{current.status}</Pill></div>
              <div className="grid g2" style={{ gap: 10 }}>
                <div className="stat"><div className="label">Starting</div><div className="value" style={{ fontSize: 18 }}>{money(current.startingCapital)}</div></div>
                <div className="stat"><div className="label">Target</div><div className="value" style={{ fontSize: 18 }}>{money(current.targetCapital)}</div></div>
                <div className="stat"><div className="label">Current capital</div><div className="value" style={{ fontSize: 18 }}>{money(current.currentCapital)}</div></div>
                <div className="stat"><div className="label">Remaining</div><div className="value" style={{ fontSize: 18 }}>{money(current.remaining)}</div></div>
                <div className="stat"><div className="label">Realized profit</div><div className={`value ${tone(current.realizedProfit)}`} style={{ fontSize: 18 }}>{signed(current.realizedProfit)}</div></div>
                <div className="stat"><div className="label">Unrealized (open)</div><div className={`value ${tone(current.unrealizedProfit)}`} style={{ fontSize: 18 }}>{signed(current.unrealizedProfit)}</div></div>
              </div>
              <div className="tiny muted">Started {when(current.startedAt)} · compounding {current.compounding ? 'on' : 'off'}. Unrealized P&L is shown separately and never counts as progress until a trade closes.</div>
              {current.status !== 'completed' && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button className="btn" disabled={busy} onClick={() => run(() => put(`/api/missions/${current.id}`, { status: current.status === 'active' ? 'paused' : 'active' }))}>{current.status === 'active' ? 'Pause mission' : 'Resume mission'}</button>
                  <button className="btn ghost" disabled={busy} onClick={() => run(() => put(`/api/missions/${current.id}`, { compounding: !current.compounding }))}>Compounding: {current.compounding ? 'ON' : 'OFF'}</button>
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      <Card title={current ? 'Start a new mission' : 'Create your first mission'}>
        <div className="stack">
          <div className="chips">{PRESETS.map(([a, b]) => <button key={a + '-' + b} className="chip" style={Number(start) === a && Number(target) === b ? { color: 'var(--text)', borderColor: 'var(--accent)' } : undefined} onClick={() => { setStart(String(a)); setTarget(String(b)); }}>${a} → ${b}</button>)}</div>
          <div className="grid g2">
            <Field label="Starting capital (USD)"><input className="input" inputMode="decimal" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="Target capital (USD)" hint={mult > 0 ? `${mult.toFixed(1)}x growth` : undefined}><input className="input" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
          </div>
          <label className="row small" style={{ justifyContent: 'flex-start', gap: 10 }}><input type="checkbox" checked={compound} onChange={(e) => setCompound(e.target.checked)} />Automatic profit compounding</label>
          {mult >= 10 && <Banner kind="warn">A {mult.toFixed(0)}x target is very aggressive. Position size never increases because a mission is progressing; it always follows your risk settings and exchange minimums, so large targets can take a long time or not be reached.</Banner>}
          <button className="btn primary" disabled={busy || !(Number(start) > 0 && Number(target) > Number(start))} onClick={create}>{current ? 'Start new mission' : 'Create mission'}</button>
          {current && current.status !== 'completed' && <div className="tiny muted">Starting a new mission pauses the current one.</div>}
        </div>
      </Card>

      {history.length > 0 && (
        <Card title="Previous missions">
          <div className="list">{history.map((m) => (
            <div key={m.id} className="item"><div className="l"><b>{money(m.startingCapital)} → {money(m.targetCapital)}</b><div className="tiny muted">{when(m.startedAt)}</div></div>
              <div className="r"><Pill tone={m.status === 'completed' ? 'blue' : 'gray'}>{m.status}</Pill><div className="tiny muted">{m.progressPct.toFixed(0)}%</div></div></div>))}</div>
        </Card>
      )}
    </div>
  );
}
