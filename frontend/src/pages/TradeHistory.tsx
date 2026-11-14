import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { TradeRecord } from '../types';

export default function TradeHistory() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);

  useEffect(() => {
    const load = async () => {
      try { setTrades((await apiFetch<{ trades: TradeRecord[] }>('/api/trades?limit=200')).trades); } catch { /* noop */ }
    };
    load();
  }, []);

  const cls = (n: number) => (n >= 0 ? 'pos' : 'neg');

  return (
    <div>
      <h1 className="page-title">Trade History</h1>
      <div className="card">
        {trades.length === 0 ? <p className="empty">No trades recorded yet.</p> : (
          <table>
            <thead><tr><th>Time</th><th>Exchange</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Fees</th><th>Status</th></tr></thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td>{new Date(t.created_at).toLocaleString()}</td>
                  <td>{t.exchange}</td>
                  <td>{t.symbol}</td>
                  <td className={t.side === 'long' ? 'pos' : 'neg'}>{t.side.toUpperCase()}</td>
                  <td>{t.qty}</td>
                  <td>{t.entry_price}</td>
                  <td>{t.exit_price ?? '—'}</td>
                  <td className={cls(t.realized_pnl)}>${t.realized_pnl.toFixed(4)}</td>
                  <td>${t.fees.toFixed(4)}</td>
                  <td>{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
