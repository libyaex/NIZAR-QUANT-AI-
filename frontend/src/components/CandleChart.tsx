import { useEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode, IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts';
import type { ChartData } from '../types';

type Line = { time: number; value: number }[];
const toLine = (l: Line) => l.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));

export default function CandleChart({ data, showEma, showVwap, showBands }: { data: ChartData | null; showEma: boolean; showVwap: boolean; showBands: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ candles?: ISeriesApi<'Candlestick'>; vol?: ISeriesApi<'Histogram'>; lines: Record<string, ISeriesApi<'Line'>> }>({ lines: {} });
  const fitted = useRef('');

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#8a94a6', fontSize: 11 },
      grid: { vertLines: { color: '#171c26' }, horzLines: { color: '#171c26' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#222a37' },
      timeScale: { borderColor: '#222a37', timeVisible: true, secondsVisible: false },
    });
    chart.current = c;
    const s = series.current;
    s.candles = c.addCandlestickSeries({ upColor: '#2fd18f', downColor: '#ff5d6c', borderVisible: false, wickUpColor: '#2fd18f', wickDownColor: '#ff5d6c' });
    s.vol = c.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
    c.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const mk = (color: string, width: 1 | 2 = 1, dash = false) =>
      c.addLineSeries({ color, lineWidth: width, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: dash ? 2 : 0 });
    s.lines = { ema9: mk('#5b9cff', 2), ema21: mk('#f5b94a', 2), vwap: mk('#c084fc'), bbUpper: mk('#4b5567', 1, true), bbLower: mk('#4b5567', 1, true) };
    return () => { c.remove(); chart.current = null; series.current = { lines: {} }; fitted.current = ''; };
  }, []);

  useEffect(() => {
    const s = series.current;
    if (!data || !s.candles || !s.vol) return;
    s.candles.setData(data.candles.map((k) => ({ time: k.time as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close })));
    s.vol.setData(data.candles.map((k) => ({ time: k.time as UTCTimestamp, value: k.volume, color: k.close >= k.open ? 'rgba(47,209,143,.28)' : 'rgba(255,93,108,.28)' })));
    const vis: Record<string, boolean> = { ema9: showEma, ema21: showEma, vwap: showVwap, bbUpper: showBands, bbLower: showBands };
    (Object.keys(s.lines) as (keyof ChartData['overlays'])[]).forEach((k) => s.lines[k].setData(vis[k] ? toLine(data.overlays[k]) : []));
    const key = `${data.exchange}|${data.symbol}|${data.timeframe}`;
    if (fitted.current !== key) { chart.current?.timeScale().fitContent(); fitted.current = key; }
  }, [data, showEma, showVwap, showBands]);

  return <div ref={box} className="chart-box" />;
}
