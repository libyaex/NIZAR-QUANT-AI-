import { useState } from 'react';
import { usePoll, useSession } from '../lib/api';
import type { Trade } from '../types';
import { Card, Empty, Pill, Seg, Skeleton } from '../components/ui';
import { SignInCta } from '../components/shared';
import { price, shortSym, signed, tone, when } from '../lib/format';

export default function History() {
  const { session } = useSession();
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const { data } = usePoll<{ trades: Trade[] }>(session ? `/api/trades?limit=200&mode=${mode}` : null, 10000);
  if (!session) return <div className="page"><SignInCta /></div>;
  const rows = data?.trades;
  return (
    <div className="page">
      <div className="page-head"><div><h1>Trade History</h1><p>Recorded executions only — nothing is simulated in this list except what is labelled paper.</p></div>
        <Seg value={mode} onChange={setMode} options={[{ v: 'paper', label: 'Paper' }, { v: 'live', label: 'Live' }]} /></div>
      {!rows ? <Skeleton h={220} /> : rows.length === 0 ? <Card><Empty>No closed {mode} trades yet</Empty></Card> : (
        <Card>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Closed</th><th>Market</th><th>Side</th><th>Entry</th><th>Exit</th><th>Fees</th><th>Net P&L</th><th>Exit reason</th></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td className="muted">{when(t.closed_at || t.created_at)}</td><td><b>{shortSym(t.symbol)}</b> <span className="tiny muted">{t.exchange}</span></td>
                    <td><Pill tone={t.side === 'long' ? 'green' : 'red'}>{t.side.toUpperCase()}</Pill></td>
                    <td className="mono">{price(Number(t.entry_price))}</td><td className="mono">{price(Number(t.exit_price))}</td>
                    <td className="mono muted">{Number(t.fees).toFixed(4)}</td>
                    <td className={`mono ${tone(Number(t.realized_pnl))}`}><b>{signed(Number(t.realized_pnl), 4)}</b></td>
                    <td className="muted small">{(t.notes || '').split('|').pop()?.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
