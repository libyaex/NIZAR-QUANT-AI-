import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { Performance } from '../types';

function Stat({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="card">
      <h3>{label}</h3>
      <div className={`stat-value ${cls ?? ''}`}>{value}</div>
    </div>
  );
}

export default function PerformancePage() {
  const [perf, setPerf] = useState<Performance | null>(null);

  useEffect(() => {
    const load = async () => {
      try { setPerf(await apiFetch<Performance>('/api/performance')); } catch { /* noop */ }
    };
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  if (!perf) return <div><h1 className="page-title">Performance</h1><p className="empty">Loading…</p></div>;

  const cls = (n: number) => (n >= 0 ? 'pos' : 'neg');

  return (
    <div>
      <h1 className="page-title">Performance Analytics</h1>
      <div className="grid cols-4">
        <Stat label="Total Trades" value={String(perf.totalTrades)} />
        <Stat label="Win Rate" value={perf.winRate.toFixed(2) + '%'} />
        <Stat label="Net P&L" value={'$' + perf.netPnl.toFixed(2)} cls={cls(perf.netPnl)} />
        <Stat label="Profit Factor" value={perf.profitFactor === Infinity ? 'INF' : perf.profitFactor.toFixed(2)} />
        <Stat label="Avg Profit" value={'$' + perf.avgProfit.toFixed(4)} cls="pos" />
        <Stat label="Avg Loss" value={'$' + perf.avgLoss.toFixed(4)} cls="neg" />
        <Stat label="Max Drawdown" value={'$' + perf.maxDrawdown.toFixed(2)} cls="neg" />
        <Stat label="Total Fees" value={'$' + perf.totalFees.toFixed(2)} />
        <Stat label="Today P&L" value={'$' + perf.todayPnl.toFixed(2)} cls={cls(perf.todayPnl)} />
        <Stat label="This Week P&L" value={'$' + perf.weekPnl.toFixed(2)} cls={cls(perf.weekPnl)} />
        {perf.futures && <Stat label="Futures Trades" value={perf.futures.trades + ' · ' + perf.futures.winRate + '%'} />}
        {perf.spot && <Stat label="Spot Trades" value={perf.spot.trades + ' · ' + perf.spot.winRate + '%'} />}
      </div>
    </div>
  );
}
