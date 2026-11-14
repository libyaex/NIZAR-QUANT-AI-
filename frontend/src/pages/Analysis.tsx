import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { Opportunity } from '../types';

export default function Analysis() {
  const [opps, setOpps] = useState<Opportunity[]>([]);
  const [sel, setSel] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        const r = await apiFetch<{ opportunities: Opportunity[] }>('/api/scanner?limit=10');
        setOpps(r.opportunities);
      } catch { /* engine may not be ready */ }
    };
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const selected = opps.find((o) => o.symbol === sel) ?? opps[0] ?? null;

  return (
    <div>
      <h1 className="page-title">Trading Analysis</h1>
      <div className="grid cols-2">
        <div className="card">
          <h3>Select Opportunity</h3>
          {opps.length === 0 ? <p className="empty">No qualified opportunities right now.</p> : (
            <table>
              <thead><tr><th>Symbol</th><th>Signal</th><th>Score</th></tr></thead>
              <tbody>
                {opps.map((o) => (
                  <tr key={o.symbol} onClick={() => setSel(o.symbol)} style={{ cursor: 'pointer' }}>
                    <td>{o.symbol}</td>
                    <td className={o.decision === 'LONG' ? 'pos' : 'neg'}>{o.decision}</td>
                    <td>{o.score.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          {selected ? (
            <div>
              <h3>{selected.symbol} — Next-Candle Probability</h3>
              <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 14 }}>
                <div><div className="stat-value pos">{(selected.bullProb * 100).toFixed(1)}%</div><div className="stat-label">Bullish</div></div>
                <div><div className="stat-value neg">{(selected.bearProb * 100).toFixed(1)}%</div><div className="stat-label">Bearish</div></div>
                <div><div className="stat-value">{selected.expectedRangePct.toFixed(3)}%</div><div className="stat-label">Expected Range</div></div>
                <div><div className="stat-value">{selected.atrPct.toFixed(3)}%</div><div className="stat-label">ATR</div></div>
                <div><div className="stat-value">{selected.spreadPct.toFixed(3)}%</div><div className="stat-label">Spread</div></div>
              </div>
              <h3>Detected Factors</h3>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {selected.reasons.map((r) => (
                  <span key={r} className="status-badge amber" style={{ fontSize: 11 }}>{r.split('_').join(' ')}</span>
                ))}
              </div>
              <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 12 }}>
                Probabilities are statistical estimates from live market data, not guaranteed outcomes.
              </p>
            </div>
          ) : <p className="empty">Select an opportunity to view analysis.</p>}
        </div>
      </div>
    </div>
  );
}
