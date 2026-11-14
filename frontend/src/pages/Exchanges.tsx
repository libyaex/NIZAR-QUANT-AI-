import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { ExchangeStatus } from '../types';

const EXCHANGES = ['binance', 'mexc', 'bybit', 'okx', 'bitget'];

export default function Exchanges() {
  const [list, setList] = useState<ExchangeStatus[]>([]);
  const [exchange, setExchange] = useState('binance');
  const [apiKey, setApiKey] = useState('');
  const [secret, setSecret] = useState('');
  const [password, setPassword] = useState('');
  const [product, setProduct] = useState('futures');
  const [testnet, setTestnet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const load = async () => {
    try { setList(await apiFetch<ExchangeStatus[]>('/api/exchanges')); } catch { /* noop */ }
  };

  useEffect(() => { load(); }, []);

  const connect = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg('');
    try {
      await apiFetch('/api/exchanges', {
        method: 'POST',
        body: JSON.stringify({
          exchange,
          label: 'default',
          apiKey,
          secret,
          password: password || undefined,
          product,
          testnet,
        }),
      });
      setApiKey(''); setSecret(''); setPassword('');
      setMsg('Connected. Keys are encrypted server-side and never returned to this browser.');
      await load();
    } catch (err) {
      setMsg('Error: ' + (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm('Disconnect this exchange and delete stored credentials?')) return;
    await apiFetch('/api/exchanges/' + id, { method: 'DELETE' });
    await load();
  };

  return (
    <div>
      <h1 className="page-title">Exchange Management</h1>
      <div className="grid cols-2">
        <div className="card">
          <h3>Connect API Keys</h3>
          <form onSubmit={connect}>
            <div className="form-row">
              <label>Exchange</label>
              <select value={exchange} onChange={(e) => setExchange(e.target.value)}>
                {EXCHANGES.map((x) => <option key={x} value={x}>{x.toUpperCase()}</option>)}
              </select>
            </div>
            <div className="form-row">
              <label>Product</label>
              <select value={product} onChange={(e) => setProduct(e.target.value)}>
                <option value="futures">Futures (primary)</option>
                <option value="spot">Spot</option>
              </select>
            </div>
            <div className="form-row">
              <label>API Key</label>
              <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)} required autoComplete="off" />
            </div>
            <div className="form-row">
              <label>Secret</label>
              <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} required autoComplete="off" />
            </div>
            {exchange === 'okx' && (
              <div className="form-row">
                <label>Passphrase (OKX)</label>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
              </div>
            )}
            <div className="form-row">
              <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="checkbox" style={{ width: 'auto' }} checked={testnet} onChange={(e) => setTestnet(e.target.checked)} />
                Use testnet
              </label>
            </div>
            <button className="btn primary" disabled={busy}>Connect</button>
          </form>
          {msg && <p style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 10 }}>{msg}</p>}
          <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 10 }}>
            Create keys with trading permission enabled and withdrawal permission DISABLED. Secrets are encrypted at rest.
          </p>
        </div>

        <div className="card">
          <h3>Connected Exchanges</h3>
          {list.length === 0 ? <p className="empty">No exchanges connected.</p> : (
            <table>
              <thead><tr><th>Exchange</th><th>Product</th><th>Testnet</th><th>Status</th><th>Markets</th><th></th></tr></thead>
              <tbody>
                {list.map((x) => (
                  <tr key={x.id}>
                    <td>{x.exchange.toUpperCase()}</td>
                    <td>{x.product}</td>
                    <td>{x.testnet ? 'yes' : 'no'}</td>
                    <td><span className={`status-badge ${x.connected ? 'green' : 'red'}`}><span className="dot" />{x.connected ? 'Connected' : 'Offline'}</span></td>
                    <td>{x.markets}</td>
                    <td><button className="btn small danger" onClick={() => remove(x.id)}>Disconnect</button></td>
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
