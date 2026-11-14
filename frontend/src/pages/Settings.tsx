import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { RiskSettings, ScannerConfig } from '../types';

const RISK_FIELDS: Array<{ key: keyof RiskSettings; label: string; step: string }> = [
  { key: 'riskPerTradePct', label: 'Risk per trade (%)', step: '0.1' },
  { key: 'maxConcurrentPositions', label: 'Max simultaneous positions', step: '1' },
  { key: 'maxDailyLossPct', label: 'Max daily loss (%)', step: '0.5' },
  { key: 'maxDrawdownPct', label: 'Max drawdown (%)', step: '1' },
  { key: 'maxLeverage', label: 'Max leverage (x)', step: '1' },
  { key: 'stopLossPct', label: 'Stop-loss distance (%)', step: '0.05' },
  { key: 'takeProfitPct', label: 'Take-profit target (%)', step: '0.05' },
  { key: 'trailingStopPct', label: 'Trailing stop (%)', step: '0.05' },
  { key: 'partialTakeProfitPct', label: 'Partial take-profit (%)', step: '5' },
  { key: 'maxHoldingMinutes', label: 'Max holding (minutes)', step: '1' },
  { key: 'consecutiveLossLimit', label: 'Consecutive loss limit', step: '1' },
  { key: 'minOpportunityScore', label: 'Min opportunity score (0-1)', step: '0.05' },
];

export default function Settings() {
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [scanner, setScanner] = useState<ScannerConfig | null>(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        setRisk(await apiFetch<RiskSettings>('/api/settings/risk'));
        setScanner(await apiFetch<ScannerConfig>('/api/settings/scanner'));
      } catch { /* noop */ }
    };
    load();
  }, []);

  const save = async () => {
    if (!risk || !scanner) return;
    setMsg('');
    try {
      await apiFetch('/api/settings/risk', { method: 'PUT', body: JSON.stringify(risk) });
      await apiFetch('/api/settings/scanner', { method: 'PUT', body: JSON.stringify(scanner) });
      setMsg('Saved.');
    } catch (e) {
      setMsg('Error: ' + (e as Error).message);
    }
  };

  if (!risk || !scanner) return <div><h1 className="page-title">Settings</h1><p className="empty">Loading…</p></div>;

  return (
    <div>
      <h1 className="page-title">Risk Management & Settings</h1>
      <div className="grid cols-2">
        <div className="card">
          <h3>Risk Management</h3>
          {RISK_FIELDS.map((f) => (
            <div className="form-row" key={f.key}>
              <label>{f.label}</label>
              <input
                type="number" step={f.step}
                value={String(risk[f.key])}
                onChange={(e) => setRisk({ ...risk, [f.key]: Number(e.target.value) })}
              />
            </div>
          ))}
        </div>
        <div className="card">
          <h3>Scanner Configuration</h3>
          <div className="form-row">
            <label>Max scanned symbols</label>
            <input type="number" value={scanner.maxSymbols}
              onChange={(e) => setScanner({ ...scanner, maxSymbols: Number(e.target.value) })} />
          </div>
          <div className="form-row">
            <label>Min 24h volume (USD)</label>
            <input type="number" value={scanner.minVolumeUsd}
              onChange={(e) => setScanner({ ...scanner, minVolumeUsd: Number(e.target.value) })} />
          </div>
          <div className="form-row">
            <label>Max spread (%)</label>
            <input type="number" step="0.01" value={scanner.maxSpreadPct}
              onChange={(e) => setScanner({ ...scanner, maxSpreadPct: Number(e.target.value) })} />
          </div>
          <div className="form-row">
            <label>Primary timeframe</label>
            <select value={scanner.primaryTimeframe}
              onChange={(e) => setScanner({ ...scanner, primaryTimeframe: e.target.value })}>
              <option value="1m">1m (primary)</option>
              <option value="2m">2m</option>
            </select>
          </div>
          <div style={{ marginTop: 18 }}>
            <button className="btn primary" onClick={save}>Save All Settings</button>
            {msg && <p style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 8 }}>{msg}</p>}
          </div>
          <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 14 }}>
            Risk limits are enforced server-side and cannot be overridden by signals.
          </p>
        </div>
      </div>
    </div>
  );
}
