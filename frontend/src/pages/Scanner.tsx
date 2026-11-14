import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { Opportunity } from '../types';

export default function Scanner() {
  const [opps, setOpps] = useState<Opportunity[]>([]);
  const [raw, setRaw] = useState<Array<Record<string, unknown>>>([]);

  const load = async () => {
    try {
      const [sig, r] = await Promise.all([
        apiFetch<{ opportunities: Opportunity[] }>('/api/scanner?limit=20'),
        apiFetch<{ results: Array<Record<string, unknown>> }>('/api/scanner/raw'),
      ]);
      setOpps(sig.opportunities);
      setRaw(r.results);
    } catch { /* engine may not be ready */ }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const fmt = (n: number) => n.toFixed(4);

  return (
    <div>
      <h1 className="page-title">Market Scanner</h1>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Qualified Opportunities</h3>
        {opps.length === 0 ? <p className="empty">Scanning markets — no opportunities above threshold yet.</p> : (
          <table>
            <thead>
              <tr><th>Symbol</th><th>Exchange</th><th>Signal</th><th>Score</th><th>Bull %</th><th>Bear %</th><th>Exp. Range %</th><th>Spread %</th><th>Reasons</th></tr>
            </thead>
            <tbody>
              {opps.map((o) => (
                <tr key={o.symbol + o.ts}>
                  <td>{o.symbol}</td>
                  <td>{o.exchange}</td>
                  <td className={o.decision === 'LONG' ? 'pos' : 'neg'}>{o.decision}</td>
                  <td>{fmt(o.score)}</td>
                  <td>{(o.bullProb * 100).toFixed(1)}</td>
                  <td>{(o.bearProb * 100).toFixed(1)}</td>
                  <td>{fmt(o.expectedRangePct)}</td>
                  <td>{fmt(o.spreadPct)}</td>
                  <td style={{ fontSize: 11, color: 'var(--text-dim)' }}>{o.reasons.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h3>Scan Results (Raw Liquidity / Volatility)</h3>
        {raw.length === 0 ? <p className="empty">No scan data yet.</p> : (
          <table>
            <thead><tr><th>Symbol</th><th>Volume (USD)</th><th>ATR %</th><th>Spread %</th><th>Rel. Volume</th><th>Score</th></tr></thead>
            <tbody>
              {raw.map((r, i) => (
                <tr key={i}>
                  <td>{String(r.symbol)}</td>
                  <td>{Number(r.volumeUsd).toLocaleString()}</td>
                  <td>{String(r.atrPct)}</td>
                  <td>{String(r.spreadPct)}</td>
                  <td>{String(r.relativeVolume)}</td>
                  <td>{String(r.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
