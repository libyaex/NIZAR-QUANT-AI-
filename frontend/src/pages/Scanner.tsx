import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { usePoll } from '../lib/api';
import type { FeedStatus, Opportunity } from '../types';
import { Card, DecisionPill, Empty, Seg, Skeleton } from '../components/ui';
import { analysisLink, FeedStrip } from '../components/shared';
import { compact, pct, price, shortSym, tone } from '../lib/format';

type Filter = 'signals' | 'LONG' | 'SHORT' | 'all';

export default function Scanner() {
  const { data, loading } = usePoll<{ opportunities: Opportunity[]; exchanges: FeedStatus[] }>('/api/scanner?limit=300&all=true', 6000);
  const [filter, setFilter] = useState<Filter>('signals');
  const [ex, setEx] = useState('all');
  const nav = useNavigate();

  const rows = useMemo(() => (data?.opportunities ?? []).filter((o) =>
    (ex === 'all' || o.exchange === ex) &&
    (filter === 'all' || (filter === 'signals' ? o.decision !== 'HOLD' : o.decision === filter))), [data, filter, ex]);
  const exchanges = data?.exchanges ?? [];

  return (
    <div className="page">
      <div className="page-head"><div><h1>Market Scanner</h1><p>Liquid USDT perpetuals ranked by volume, spread, volatility and setup quality.</p></div></div>
      <div className="row" style={{ flexWrap: 'wrap', justifyContent: 'flex-start' }}>
        <Seg<Filter> value={filter} onChange={setFilter} options={[{ v: 'signals', label: 'Signals' }, { v: 'LONG', label: 'Long' }, { v: 'SHORT', label: 'Short' }, { v: 'all', label: 'All markets' }]} />
        <Seg<string> value={ex} onChange={setEx} options={[{ v: 'all', label: 'All' }, ...exchanges.filter((e) => e.status === 'ok').map((e) => ({ v: e.id, label: e.id.toUpperCase() }))]} />
      </div>
      {loading && !data ? <Skeleton h={300} /> : rows.length === 0 ? (
        <Card><Empty>{filter === 'signals' ? 'No market passes every filter right now. That is normal — the bot waits for clean setups. Switch to "All markets" to see why each one was rejected.' : 'Nothing to show.'}</Empty></Card>
      ) : (
        <>
          <Card className="only-desktop">
            <div className="table-wrap">
              <table>
                <thead><tr><th>Market</th><th>Exchange</th><th>Signal</th><th>Score</th><th>Price</th><th>24h</th><th>Spread</th><th>ATR</th><th>Rel vol</th><th>24h vol</th><th>Why</th></tr></thead>
                <tbody>
                  {rows.map((o) => (
                    <tr key={o.exchange + o.symbol} className="click" onClick={() => nav(analysisLink(o))}>
                      <td><b>{shortSym(o.symbol)}</b></td><td className="muted">{o.exchange.toUpperCase()}</td>
                      <td><DecisionPill d={o.decision} /></td>
                      <td><div style={{ width: 70 }}><div className="bar"><i style={{ width: `${o.score * 100}%`, background: o.decision === 'SHORT' ? 'var(--short)' : o.decision === 'LONG' ? 'var(--long)' : 'var(--faint)' }} /></div></div></td>
                      <td className="mono">{price(o.price)}</td><td className={`mono ${tone(o.change24hPct)}`}>{pct(o.change24hPct)}</td>
                      <td className="mono">{pct(o.spreadPct, 3)}</td><td className="mono">{pct(o.atrPct, 3)}</td><td className="mono">{o.relativeVolume.toFixed(1)}x</td>
                      <td className="mono">${compact(o.volumeUsd)}</td>
                      <td className="muted small" style={{ whiteSpace: 'normal', minWidth: 200 }}>{o.reasons.slice(-2).join(' · ').replace(/_/g, ' ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card className="only-mobile">
            <div className="list">
              {rows.map((o) => (
                <Link key={o.exchange + o.symbol} to={analysisLink(o)} className="item">
                  <div className="l">
                    <div className="sym">{shortSym(o.symbol)}<small>{o.exchange.toUpperCase()}</small></div>
                    <div className="tiny muted mono">{price(o.price)} · <span className={tone(o.change24hPct)}>{pct(o.change24hPct, 1)}</span> · spread {pct(o.spreadPct, 3)}</div>
                    <div className="tiny muted">{o.reasons.slice(-1)[0]?.replace(/_/g, ' ')}</div>
                  </div>
                  <div className="r"><DecisionPill d={o.decision} /><div className="tiny muted mono" style={{ marginTop: 4 }}>{o.score.toFixed(2)}</div></div>
                </Link>
              ))}
            </div>
          </Card>
        </>
      )}
      <Card title="Data sources">{exchanges.length ? <FeedStrip feeds={exchanges} /> : <Skeleton h={30} />}</Card>
    </div>
  );
}
