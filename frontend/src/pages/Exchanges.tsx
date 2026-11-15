import { useState } from 'react';
import { FormEvent } from 'react';
import { del, post, usePoll, useSession } from '../lib/api';
import type { ExchangeCfg, FeedStatus } from '../types';
import { Banner, Card, Empty, Field, Pill } from '../components/ui';
import { ago } from '../lib/format';

const NEEDS_PASS = ['okx', 'bitget'];

export default function Exchanges() {
  const { session } = useSession();
  const feeds = usePoll<{ exchanges: FeedStatus[] }>('/api/market?limit=1', 6000);
  const cfgs = usePoll<ExchangeCfg[]>(session ? '/api/exchanges' : null, 10000);
  const [f, setF] = useState({ exchange: 'bybit', label: 'main', apiKey: '', secret: '', password: '', product: 'futures', testnet: false });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'err' | 'ok'; text: string } | null>(null);

  const connect = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      const r = await post<ExchangeCfg>('/api/exchanges', { ...f, password: f.password || null });
      setMsg(r.connected ? { kind: 'ok', text: `${r.exchange.toUpperCase()} connected (${r.markets} markets).` } : { kind: 'err', text: `Saved, but connection failed: ${r.lastError ?? 'unknown error'}` });
      setF({ ...f, apiKey: '', secret: '', password: '' });
      await cfgs.reload();
    } catch (err) { setMsg({ kind: 'err', text: (err as Error).message }); } finally { setBusy(false); }
  };
  const remove = async (id: string) => {
    if (!confirm('Disconnect and permanently delete these credentials?')) return;
    try { await del(`/api/exchanges/${id}`); await cfgs.reload(); } catch (err) { setMsg({ kind: 'err', text: (err as Error).message }); }
  };
  const set = (k: string, v: string | boolean) => setF({ ...f, [k]: v });

  return (
    <div className="page">
      <div className="page-head"><div><h1>Exchange Management</h1><p>Market data needs no keys. Keys are only for Live trading.</p></div></div>
      <Card title="Market data feeds (no keys required)">
        <div className="list">
          {(feeds.data?.exchanges ?? []).map((x) => (
            <div key={x.id} className="item" style={{ alignItems: 'flex-start' }}>
              <div className="l"><b>{x.id.toUpperCase()}</b>
                {x.status === 'ok' && <div className="tiny muted">{x.symbols} perpetuals · {x.scanned} scanned · {x.signals} signals · last scan {ago(x.lastScanAgoSec)} · ws {x.ws.connected ? 'live' : 'off'}</div>}
                {x.status === 'error' && <div className="tiny neg" style={{ whiteSpace: 'normal' }}>{x.error}</div>}
                {x.hint && <div className="tiny warn" style={{ whiteSpace: 'normal', marginTop: 3 }}>{x.hint}</div>}</div>
              <Pill tone={x.status === 'ok' ? 'green' : x.status === 'error' ? 'red' : 'amber'} dot>{x.status === 'ok' ? 'Live' : x.status === 'error' ? 'Error' : 'Starting'}</Pill>
            </div>
          ))}
          {!feeds.data && <Empty>Loading…</Empty>}
        </div>
      </Card>

      {!session ? <Banner kind="warn">Sign in to connect exchange accounts.</Banner> : (
        <>
          <Card title="Connected accounts">
            {!cfgs.data?.length ? <Empty>No exchange account connected. Paper trading works without one.</Empty> : (
              <div className="list">{cfgs.data.map((c) => (
                <div key={c.id} className="item"><div className="l"><b>{c.exchange.toUpperCase()}</b> <span className="muted small">{c.label} · {c.product}{c.testnet ? ' · testnet' : ''}</span>
                  {c.lastError && !c.connected && <div className="tiny neg" style={{ whiteSpace: 'normal' }}>{c.lastError}</div>}</div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Pill tone={c.connected ? 'green' : 'red'} dot>{c.connected ? 'Connected' : 'Failed'}</Pill>
                    <button className="btn sm danger" onClick={() => remove(c.id)}>Remove</button></div></div>))}</div>
            )}
          </Card>
          <Card title="Connect an exchange">
            <form className="stack" onSubmit={connect}>
              <Banner kind="warn"><div>Create the API key with <b>Read + Trade</b> permission and <b>withdrawals disabled</b>. Restrict it to your Railway server IP if the exchange allows. Secrets are encrypted on the server and never sent back to the browser.</div></Banner>
              {msg && <Banner kind={msg.kind}>{msg.text}</Banner>}
              <div className="grid g2">
                <Field label="Exchange"><select className="input" value={f.exchange} onChange={(e) => set('exchange', e.target.value)}>{['binance', 'bybit', 'okx', 'bitget', 'mexc'].map((x) => <option key={x} value={x}>{x.toUpperCase()}</option>)}</select></Field>
                <Field label="Product"><select className="input" value={f.product} onChange={(e) => set('product', e.target.value)}><option value="futures">Futures (perpetual)</option><option value="spot">Spot</option></select></Field>
                <Field label="Label"><input className="input" value={f.label} onChange={(e) => set('label', e.target.value)} /></Field>
                <Field label="API key"><input className="input" required autoComplete="off" value={f.apiKey} onChange={(e) => set('apiKey', e.target.value)} /></Field>
                <Field label="API secret"><input className="input" required type="password" autoComplete="off" value={f.secret} onChange={(e) => set('secret', e.target.value)} /></Field>
                {NEEDS_PASS.includes(f.exchange) && <Field label="API passphrase"><input className="input" required type="password" autoComplete="off" value={f.password} onChange={(e) => set('password', e.target.value)} /></Field>}
              </div>
              <label className="row small" style={{ justifyContent: 'flex-start', gap: 10 }}><input type="checkbox" checked={f.testnet} onChange={(e) => set('testnet', e.target.checked)} />Use exchange testnet / sandbox</label>
              <button className="btn primary" disabled={busy}>{busy ? 'Verifying credentials…' : 'Connect & verify'}</button>
            </form>
          </Card>
        </>
      )}
    </div>
  );
}
