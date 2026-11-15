import { Link } from 'react-router-dom';
import type { FeedStatus, Opportunity, Position } from '../types';
import { Card, DecisionPill, Empty, Pill } from './ui';
import { money, price, shortSym, signed, tone } from '../lib/format';

export const analysisLink = (o: { exchange: string; symbol: string }) =>
  `/analysis?exchange=${o.exchange}&symbol=${encodeURIComponent(o.symbol)}`;

export function SignInCta() {
  return (
    <Card>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <div><b>Sign in to trade</b><div className="muted small">Live market data is shown below. Sign in to start the bot, manage missions and connect exchanges.</div></div>
        <Link to="/auth" className="btn primary">Sign in</Link>
      </div>
    </Card>
  );
}

export function OpportunityList({ items, empty = 'Scanning markets…' }: { items: Opportunity[]; empty?: string }) {
  if (!items.length) return <Empty>{empty}</Empty>;
  return (
    <div className="list">
      {items.map((o) => (
        <Link key={`${o.exchange}-${o.symbol}`} to={analysisLink(o)} className="item">
          <div className="l">
            <div className="sym">{shortSym(o.symbol)}<small>{o.exchange.toUpperCase()}</small></div>
            <div className="tiny muted">{o.reasons.slice(0, 2).join(' · ').replace(/_/g, ' ') || 'multi-factor setup'}</div>
          </div>
          <div className="r">
            <DecisionPill d={o.decision} />
            <div className="tiny muted mono" style={{ marginTop: 4 }}>score {o.score.toFixed(2)}</div>
          </div>
        </Link>
      ))}
    </div>
  );
}

export function PositionList({ items }: { items: Position[] }) {
  if (!items.length) return <Empty>No open positions</Empty>;
  return (
    <div className="list">
      {items.map((p) => (
        <div key={p.positionId} className="item">
          <div className="l">
            <div className="sym">{shortSym(p.symbol)}<small>{p.exchange.toUpperCase()}</small> <Pill tone={p.side === 'long' ? 'green' : 'red'}>{p.side.toUpperCase()}</Pill></div>
            <div className="tiny muted mono">entry {price(p.entryPrice)} → {price(p.markPrice)}</div>
          </div>
          <div className={`r mono ${tone(p.unrealizedPnl)}`}><b>{signed(p.unrealizedPnl, 4)}</b></div>
        </div>
      ))}
    </div>
  );
}

export function FeedStrip({ feeds }: { feeds: FeedStatus[] }) {
  return (
    <div className="chips">
      {feeds.map((f) => (
        <Pill key={f.id} tone={f.status === 'ok' ? 'green' : f.status === 'error' ? 'red' : 'amber'} dot>
          {f.id.toUpperCase()}{f.status === 'ok' ? ` · ${f.scanned}` : ''}
        </Pill>
      ))}
    </div>
  );
}
export { money };
