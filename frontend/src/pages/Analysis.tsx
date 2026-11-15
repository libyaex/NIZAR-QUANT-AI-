import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { usePoll } from '../lib/api';
import type { ChartData, FeedStatus, Opportunity } from '../types';
import CandleChart from '../components/CandleChart';
import { Card, DecisionPill, Empty, Pill, Seg, Skeleton } from '../components/ui';
import { pct, price, shortSym } from '../lib/format';

const TFS = ['1m', '2m', '3m', '5m', '15m'];
const LABEL: Record<string, string> = {
  candles: 'Candlesticks', structure: 'Structure', trend: 'Trend (EMA)', mtf: 'Higher TFs', momentum: 'Momentum',
  oscillators: 'RSI / MACD', orderflow: 'Order flow', probability: 'Next candle',
};

export default function Analysis() {
  const [params, setParams] = useSearchParams();
  const scan = usePoll<{ opportunities: Opportunity[]; exchanges: FeedStatus[] }>('/api/scanner?limit=60&all=true', 15000);
  const [tf, setTf] = useState('1m');
  const [ema, setEma] = useState(true);
  const [vwap, setVwap] = useState(true);
  const [bands, setBands] = useState(false);

  const exchange = params.get('exchange');
  const symbol = params.get('symbol');
  useEffect(() => {
    if (!symbol && scan.data?.opportunities.length) {
      const o = scan.data.opportunities[0];
      setParams({ exchange: o.exchange, symbol: o.symbol }, { replace: true });
    }
  }, [symbol, scan.data, setParams]);

  const chart = usePoll<ChartData>(exchange && symbol ? `/api/chart?exchange=${exchange}&symbol=${encodeURIComponent(symbol)}&tf=${tf}` : null, 5000);
  const a = chart.data?.analysis ?? null;
  const options = (scan.data?.opportunities ?? []).slice(0, 40);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>{symbol ? shortSym(symbol) : 'Trading Analysis'}</h1><p>{exchange?.toUpperCase()} · live candles, indicators and decision breakdown</p></div>
        <select className="input" style={{ width: 'auto', minWidth: 180 }} value={`${exchange}|${symbol}`}
          onChange={(e) => { const [x, s] = e.target.value.split('|'); setParams({ exchange: x, symbol: s }); }}>
          {symbol && !options.some((o) => o.symbol === symbol && o.exchange === exchange) && <option value={`${exchange}|${symbol}`}>{shortSym(symbol)} · {exchange}</option>}
          {options.map((o) => <option key={o.exchange + o.symbol} value={`${o.exchange}|${o.symbol}`}>{shortSym(o.symbol)} · {o.exchange} · {o.decision}</option>)}
        </select>
      </div>

      <Card>
        <div className="row" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
          <Seg value={tf} onChange={setTf} options={TFS.map((t) => ({ v: t, label: t }))} />
          <div className="chips">
            {([['EMA 9/21', ema, setEma], ['VWAP', vwap, setVwap], ['Bollinger', bands, setBands]] as const).map(([l, on, set]) => (
              <button key={l} className="chip" style={on ? { color: 'var(--text)', borderColor: 'var(--accent)' } : undefined} onClick={() => set(!on)}>{l}</button>
            ))}
          </div>
        </div>
        {chart.error && !chart.data ? <Empty>{chart.error.message}</Empty> : !chart.data ? <Skeleton h={360} /> :
          <CandleChart data={chart.data} showEma={ema} showVwap={vwap} showBands={bands} />}
      </Card>

      {a && (
        <div className="grid g2">
          <Card title="Decision" action={<DecisionPill d={a.decision} />}>
            <div className="row"><div className="stat"><div className="label">Opportunity score</div><div className="value">{a.score.toFixed(2)}</div></div>
              <Pill tone="gray">{a.agree}/8 blocks agree</Pill></div>
            {a.reject && <div className="small warn" style={{ margin: '8px 0' }}>Rejected: {a.reject}</div>}
            <div className="stack" style={{ marginTop: 12 }}>
              {Object.entries(a.components).map(([k, v]) => (
                <div className="comp" key={k}>
                  <span className="muted">{LABEL[k] ?? k}</span>
                  <div className="track"><i style={{ left: v >= 0 ? '50%' : `${50 + v * 50}%`, width: `${Math.abs(v) * 50}%`, background: v >= 0 ? 'var(--long)' : 'var(--short)' }} /></div>
                  <span className="mono tiny" style={{ textAlign: 'right' }}>{v.toFixed(2)}</span>
                </div>
              ))}
            </div>
            <div className="chips" style={{ marginTop: 14 }}>{a.reasons.map((r) => <span className="chip" key={r}>{r.replace(/_/g, ' ')}</span>)}</div>
          </Card>

          <div className="stack">
            <Card title="Next-candle probability (estimate)">
              <div className="row small"><span className="pos">Bullish {(a.prob.bullProb * 100).toFixed(1)}%</span><span className="neg">Bearish {(a.prob.bearProb * 100).toFixed(1)}%</span></div>
              <div className="split-bar" style={{ margin: '8px 0' }}><i style={{ width: `${a.prob.bullProb * 100}%`, background: 'var(--long)' }} /><i style={{ flex: 1, background: 'var(--short)' }} /></div>
              <div className="tiny muted">Source: {a.prob.source === 'blended_model' ? 'online model blended with heuristic prior' : a.prob.source === 'insufficient_data' ? 'not enough data' : 'heuristic prior (model still collecting samples)'} · confidence {(a.prob.confidence * 100).toFixed(0)}% · expected range ≈ {pct(a.prob.expectedRangePct, 3)}. Estimates, not guarantees.</div>
            </Card>
            <Card title="Indicators & structure">
              <div className="grid g3" style={{ gap: 12 }}>
                {[['RSI', a.rsi.toFixed(1)], ['Stoch RSI', a.stochRsi.toFixed(0)], ['MACD hist', a.macdHist.toPrecision(2)], ['ATR', pct(a.atrPct, 3)],
                  ['Spread', pct(a.spreadPct, 3)], ['Book imbalance', a.imbalance.toFixed(2)], ['Rel volume', `${a.relVolume.toFixed(1)}x`], ['VWAP', price(a.vwap)], ['Round-trip cost', pct(a.costPct, 3)]].map(([k, v]) => (
                  <div key={k} className="stat"><div className="label">{k}</div><div className="mono" style={{ fontWeight: 650 }}>{v}</div></div>
                ))}
              </div>
              <div className="small muted" style={{ marginTop: 12 }}>
                Bias <b style={{ color: 'var(--text)' }}>{a.structure.bias}</b> · Support {price(a.structure.support)} · Resistance {price(a.structure.resistance)}
                {a.structure.breakout && ` · breakout ${a.structure.breakout.replace('_', ' ')}`}{a.structure.falseBreakout && ` · false breakout ${a.structure.falseBreakout}`}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
