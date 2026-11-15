import { useState } from 'react';
import { usePoll, useSession } from '../lib/api';
import type { Performance as Perf } from '../types';
import { Bars, Card, LineArea, Seg, Skeleton, Stat } from '../components/ui';
import { SignInCta } from '../components/shared';
import { money, signed, tone } from '../lib/format';

export default function Performance() {
  const { session } = useSession();
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const { data: p } = usePoll<Perf>(session ? `/api/performance?mode=${mode}` : null, 15000);
  if (!session) return <div className="page"><SignInCta /></div>;
  return (
    <div className="page">
      <div className="page-head"><div><h1>Performance</h1><p>Computed from recorded trades only.</p></div>
        <Seg value={mode} onChange={setMode} options={[{ v: 'paper', label: 'Paper' }, { v: 'live', label: 'Live' }]} /></div>
      {!p ? <Skeleton h={260} /> : (
        <>
          <div className="grid g4">
            <Stat label="Net realized P&L" value={signed(p.netPnl)} cls={tone(p.netPnl)} sub={`${p.totalTrades} trades`} />
            <Stat label="Win rate" value={`${p.winRate.toFixed(1)}%`} sub={`${p.wins}W / ${p.losses}L`} />
            <Stat label="Profit factor" value={p.profitFactor.toFixed(2)} sub={`avg win ${money(p.avgProfit, 3)} · avg loss ${money(p.avgLoss, 3)}`} />
            <Stat label="Max drawdown" value={money(p.maxDrawdown)} sub={`fees paid ${money(p.totalFees, 3)}`} />
          </div>
          <Card title="Equity curve (cumulative realized P&L)"><LineArea points={p.curve.map((c) => c.pnl)} /></Card>
          <div className="grid g2">
            <Card title="Daily P&L (30 days)"><Bars items={p.daily.map((d) => ({ label: d.date, value: d.pnl }))} /></Card>
            <Card title="Weekly P&L">
              {p.weekly.length === 0 ? <div className="empty">No data yet</div> : (
                <div className="list">{[...p.weekly].reverse().map((w) => <div key={w.week} className="item"><span className="muted">Week of {w.week}</span><b className={`mono ${tone(w.pnl)}`}>{signed(w.pnl)}</b></div>)}</div>
              )}
            </Card>
          </div>
          <div className="grid g3">
            <Stat label="Today" value={signed(p.todayPnl)} cls={tone(p.todayPnl)} />
            <Stat label="Last 7 days" value={signed(p.weekPnl)} cls={tone(p.weekPnl)} />
            <Card title="By product">
              <div className="stack small">
                <div className="row"><span>Futures</span><span className="mono">{p.futures?.trades ?? 0} · {signed(p.futures?.netPnl ?? 0)} · {p.futures?.winRate ?? 0}%</span></div>
                <div className="row"><span>Spot</span><span className="mono">{p.spot?.trades ?? 0} · {signed(p.spot?.netPnl ?? 0)} · {p.spot?.winRate ?? 0}%</span></div>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
