import { useEffect, useState } from 'react';
import { put, usePoll, useSession } from '../lib/api';
import type { RiskSettings, ScannerConfig } from '../types';
import { Banner, Card, Field, Skeleton } from '../components/ui';
import { SignInCta } from '../components/shared';

type RK = keyof RiskSettings;
const RISK_FIELDS: { k: RK; label: string; hint: string; step?: number }[] = [
  { k: 'riskPerTradePct', label: 'Risk per trade (%)', hint: 'Share of equity lost if the stop-loss is hit', step: 0.1 },
  { k: 'maxConcurrentPositions', label: 'Max simultaneous positions', hint: 'Across all exchanges' },
  { k: 'maxLeverage', label: 'Max leverage (x)', hint: 'Hard cap on notional / equity' },
  { k: 'stopLossPct', label: 'Stop-loss distance (%)', hint: 'Price move against the trade', step: 0.05 },
  { k: 'takeProfitPct', label: 'Take-profit target (%)', hint: 'Must exceed round-trip fees + spread', step: 0.05 },
  { k: 'trailingStopPct', label: 'Trailing stop (%)', hint: 'Active after the partial take-profit', step: 0.05 },
  { k: 'partialTakeProfitPct', label: 'Partial take-profit (% of position)', hint: '0 disables partial exits' },
  { k: 'maxHoldingMinutes', label: 'Max holding time (min)', hint: 'Scalps are closed after this' },
  { k: 'maxDailyLossPct', label: 'Max daily loss (%)', hint: 'Halts new trades for the UTC day', step: 0.5 },
  { k: 'maxDrawdownPct', label: 'Max drawdown (%)', hint: 'From peak equity; halts until reset', step: 0.5 },
  { k: 'consecutiveLossLimit', label: 'Consecutive-loss limit', hint: 'Pause after this many losses in a row' },
  { k: 'minOpportunityScore', label: 'Min opportunity score (0–1)', hint: 'Lower = more trades, lower quality', step: 0.05 },
  { k: 'takerFeePct', label: 'Taker fee per side (%)', hint: 'Used for sizing and cost checks', step: 0.01 },
  { k: 'paperBalance', label: 'Paper account balance ($)', hint: 'Applies to Paper mode' },
];
const SCAN_FIELDS: { k: keyof ScannerConfig; label: string; hint: string; step?: number }[] = [
  { k: 'maxSymbols', label: 'Symbols per exchange', hint: 'More = slower scans' },
  { k: 'minVolumeUsd', label: 'Min 24h volume ($)', hint: 'Liquidity floor' },
  { k: 'maxSpreadPct', label: 'Max spread (%)', hint: 'Rejects costly markets', step: 0.01 },
  { k: 'minAtrPct', label: 'Min 1m volatility ATR (%)', hint: 'Rejects dead markets', step: 0.01 },
];

export default function Settings() {
  const { session } = useSession();
  const risk = usePoll<RiskSettings>(session ? '/api/settings/risk' : null, 600000);
  const scan = usePoll<ScannerConfig>(session ? '/api/settings/scanner' : null, 600000);
  const [r, setR] = useState<RiskSettings | null>(null);
  const [s, setS] = useState<ScannerConfig | null>(null);
  const [msg, setMsg] = useState<{ kind: 'err' | 'ok'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (risk.data && !r) setR(risk.data); }, [risk.data, r]);
  useEffect(() => { if (scan.data && !s) setS(scan.data); }, [scan.data, s]);
  if (!session) return <div className="page"><SignInCta /></div>;

  const save = async () => {
    if (!r || !s) return;
    setBusy(true); setMsg(null);
    try { await put('/api/settings/risk', r); await put('/api/settings/scanner', s); setMsg({ kind: 'ok', text: 'Settings saved and applied to the running engine.' }); }
    catch (e) { setMsg({ kind: 'err', text: (e as Error).message }); } finally { setBusy(false); }
  };
  const num = (v: string) => (v === '' ? 0 : Number(v));

  return (
    <div className="page">
      <div className="page-head"><div><h1>Risk & Settings</h1><p>The risk manager can never be overridden by a signal.</p></div>
        <button className="btn primary" disabled={busy || !r} onClick={save}>{busy ? 'Saving…' : 'Save changes'}</button></div>
      {msg && <Banner kind={msg.kind}>{msg.text}</Banner>}
      {!r || !s ? <Skeleton h={300} /> : (
        <>
          <Card title="Risk management">
            <div className="grid g2">
              {RISK_FIELDS.map((f) => (
                <Field key={f.k} label={f.label} hint={f.hint}>
                  <input className="input" type="number" inputMode="decimal" step={f.step ?? 1} value={r[f.k] as number} onChange={(e) => setR({ ...r, [f.k]: num(e.target.value) })} />
                </Field>
              ))}
            </div>
            <p className="tiny muted" style={{ marginTop: 12 }}>Execution mode ({r.tradingMode}) is switched on the Trade screen.</p>
          </Card>
          <Card title="Market scanner">
            <div className="grid g2">
              {SCAN_FIELDS.map((f) => (
                <Field key={f.k} label={f.label} hint={f.hint}>
                  <input className="input" type="number" inputMode="decimal" step={f.step ?? 1} value={s[f.k] as number} onChange={(e) => setS({ ...s, [f.k]: num(e.target.value) })} />
                </Field>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
