export const money = (n: number | null | undefined, digits = 2) =>
  n == null || Number.isNaN(n) ? '—' : `${n < 0 ? '-' : ''}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
export const signed = (n: number, digits = 2) => `${n > 0 ? '+' : ''}${money(n, digits)}`;
export const pct = (n: number | null | undefined, digits = 2) => (n == null ? '—' : `${n.toFixed(digits)}%`);
export const price = (n: number | null | undefined) => {
  if (n == null || !n) return '—';
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : n >= 0.1 ? 5 : 6;
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
};
export const compact = (n: number) => Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
export const tone = (n: number) => (n > 0 ? 'pos' : n < 0 ? 'neg' : '');
export const shortSym = (s: string) => s.split('/')[0];
export const ago = (sec: number | null | undefined) => (sec == null ? '—' : sec < 60 ? `${sec}s ago` : `${Math.floor(sec / 60)}m ago`);
export const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
export const duration = (sec: number) => (sec < 3600 ? `${Math.floor(sec / 60)}m` : `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`);
