import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { Position } from '../types';

export default function Positions() {
  const [positions, setPositions] = useState<Position[]>([]);

  useEffect(() => {
    const load = async () => {
      try { setPositions(await apiFetch<Position[]>('/api/positions')); } catch { /* noop */ }
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const cls = (n: number) => (n >= 0 ? 'pos' : 'neg');

  return (
    <div>
      <h1 className="page-title">Active Positions</h1>
      <div className="card">
        {positions.length === 0 ? <p className="empty">No open positions right now.</p> : (
          <table>
            <thead>
              <tr><th>Symbol</th><th>Exchange</th><th>Side</th><th>Qty</th><th>Entry</th><th>Mark</th><th>Lev</th><th>SL</th><th>TP</th><th>Trailing</th><th>Partial</th><th>Realized</th><th>Unrealized</th></tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.positionId}>
                  <td>{p.symbol}</td>
                  <td>{p.exchange}</td>
                  <td className={p.side === 'long' ? 'pos' : 'neg'}>{p.side.toUpperCase()}</td>
                  <td>{p.qty}</td>
                  <td>{p.entryPrice}</td>
                  <td>{p.markPrice}</td>
                  <td>{p.leverage}x</td>
                  <td>{p.stopLoss ?? '—'}</td>
                  <td>{p.takeProfit ?? '—'}</td>
                  <td>{p.trailingActive ? 'ON' : 'off'}</td>
                  <td>{p.partialFilled ? 'yes' : 'no'}</td>
                  <td className={cls(p.realizedPnl)}>${p.realizedPnl.toFixed(4)}</td>
                  <td className={cls(p.unrealizedPnl)}>${p.unrealizedPnl.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
