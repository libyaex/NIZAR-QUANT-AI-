import { post, usePoll, useSession } from '../lib/api';
import type { Position } from '../types';
import { Card, Empty, Pill, Skeleton } from '../components/ui';
import { SignInCta } from '../components/shared';
import { money, price, shortSym, signed, tone, when } from '../lib/format';

export default function Positions() {
  const { session } = useSession();
  const { data, reload } = usePoll<Position[]>(session ? '/api/positions' : null, 3000);
  if (!session) return <div className="page"><SignInCta /></div>;
  const total = (data ?? []).reduce((a, p) => a + p.unrealizedPnl, 0);
  return (
    <div className="page">
      <div className="page-head"><div><h1>Active Positions</h1><p>Open P&L <b className={tone(total)}>{signed(total, 4)}</b> (unrealized)</p></div>
        <button className="btn danger" disabled={!data?.length} onClick={() => confirm('Close ALL open positions?') && post('/api/trading/close-all').then(reload)}>Close all</button></div>
      {!data ? <Skeleton h={160} /> : data.length === 0 ? <Card><Empty>No open positions</Empty></Card> : (
        <div className="grid g2">
          {data.map((p) => (
            <Card key={p.positionId}>
              <div className="row"><div className="sym" style={{ fontSize: 17 }}>{shortSym(p.symbol)}<small>{p.exchange.toUpperCase()} · {p.leverage}x</small></div>
                <span style={{ display: 'flex', gap: 6 }}><Pill tone={p.side === 'long' ? 'green' : 'red'}>{p.side.toUpperCase()}</Pill><Pill tone={p.mode === 'live' ? 'red' : 'blue'}>{p.mode}</Pill></span></div>
              <div className={`mono ${tone(p.unrealizedPnl)}`} style={{ fontSize: 26, fontWeight: 750, margin: '10px 0' }}>{signed(p.unrealizedPnl, 4)}</div>
              <div className="grid g2 small" style={{ gap: 8 }}>
                <div><span className="muted">Entry</span><div className="mono">{price(p.entryPrice)}</div></div><div><span className="muted">Mark</span><div className="mono">{price(p.markPrice)}</div></div>
                <div><span className="muted">Stop</span><div className="mono neg">{price(p.stopLoss)}</div></div><div><span className="muted">Target</span><div className="mono pos">{price(p.takeProfit)}</div></div>
              </div>
              <div className="chips" style={{ marginTop: 12 }}>
                <span className="chip">opened {when(p.openedAt)}</span>
                {p.trailingActive && <span className="chip">trailing</span>}{p.partialFilled && <span className="chip">partial taken</span>}
                {p.mode === 'live' && <span className="chip" style={{ color: p.protectedOnExchange ? 'var(--long)' : 'var(--warn)' }}>{p.protectedOnExchange ? 'exchange-side SL/TP' : 'software SL/TP only'}</span>}
                {p.realizedPnl !== 0 && <span className="chip">booked {money(p.realizedPnl, 4)}</span>}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
