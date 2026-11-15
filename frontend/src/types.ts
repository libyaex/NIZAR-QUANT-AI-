export type TradingState = 'engine_ready' | 'trading_active' | 'trading_stopped' | 'connection_lost' | 'emergency_halt';
export type Decision = 'LONG' | 'SHORT' | 'HOLD';

export interface EngineStatus {
  state: TradingState; uptimeSeconds: number; exchangesConnected: string[]; scannedSymbols: number;
  openPositions: number; tradingActive: boolean; mode: 'paper' | 'live'; equity: number; haltReason: string; message: string;
}
export interface FeedStatus {
  id: string; status: 'starting' | 'ok' | 'error'; error: string; hint: string; symbols: number; scanned: number;
  signals: number; lastScanAgoSec: number | null; scanMs: number;
  ws: { connected: boolean; ticks: number; lastTickAgoSec: number | null; error: string | null };
}
export interface Opportunity {
  symbol: string; exchange: string; product: string; score: number; decision: Decision; price: number;
  change24hPct: number; momentum: number; relativeVolume: number; probSource: string; confidence: number;
  bullProb: number; bearProb: number; expectedRangePct: number; spreadPct: number; volumeUsd: number;
  atrPct: number; reasons: string[]; ts: string;
}
export interface Position {
  positionId: string; exchange: string; symbol: string; product: string; side: 'long' | 'short'; qty: number;
  entryPrice: number; markPrice: number; leverage: number; stopLoss: number | null; takeProfit: number | null;
  trailingActive: boolean; partialFilled: boolean; protectedOnExchange: boolean; mode: string;
  realizedPnl: number; unrealizedPnl: number; openedAt: string;
}
export interface Mission {
  id: string; startingCapital: number; currentCapital: number; targetCapital: number; realizedProfit: number;
  unrealizedProfit: number; remaining: number; progressPct: number; status: 'active' | 'paused' | 'completed';
  compounding: boolean; startedAt: string | null; completedAt: string | null; allowsNewTrades: boolean;
}
export interface Performance {
  totalTrades: number; wins: number; losses: number; winRate: number; netPnl: number; totalFees: number;
  avgProfit: number; avgLoss: number; profitFactor: number; maxDrawdown: number; todayPnl: number; weekPnl: number;
  spot: { trades: number; netPnl: number; winRate: number } | null;
  futures: { trades: number; netPnl: number; winRate: number } | null;
  daily: { date: string; pnl: number }[]; weekly: { week: string; pnl: number }[]; curve: { t: string; pnl: number }[];
}
export interface Dashboard {
  status: EngineStatus; positions: Position[]; unrealized: number; today: { pnl: number; trades: number };
  performance: Performance; mission: Mission | null; opportunities: Opportunity[]; exchanges: FeedStatus[];
}
export interface Trade {
  id: string; exchange: string; symbol: string; product: string; side: 'long' | 'short'; qty: number;
  entry_price: number; exit_price: number | null; realized_pnl: number; fees: number; notes: string | null;
  created_at: string; closed_at: string | null;
}
export interface RiskSettings {
  tradingMode: 'paper' | 'live'; paperBalance: number; riskPerTradePct: number; maxConcurrentPositions: number;
  maxDailyLossPct: number; maxDrawdownPct: number; maxLeverage: number; stopLossPct: number; takeProfitPct: number;
  trailingStopPct: number; partialTakeProfitPct: number; maxHoldingMinutes: number; consecutiveLossLimit: number;
  minOpportunityScore: number; takerFeePct: number;
}
export interface ScannerConfig { maxSymbols: number; minVolumeUsd: number; maxSpreadPct: number; minAtrPct: number; }
export interface ExchangeCfg {
  id: string; exchange: string; label: string; product: string; testnet: boolean; connected: boolean;
  markets: number; lastError: string | null; createdAt: string | null;
}
export interface Analysis {
  decision: Decision; direction: Decision; score: number; edge: number; agree: number; reasons: string[]; reject: string | null;
  components: Record<string, number>; price: number; atrPct: number; spreadPct: number; imbalance: number;
  relVolume: number; momentum: number; rsi: number; macdHist: number; stochRsi: number; bbPos: number; vwap: number; costPct: number;
  prob: { bullProb: number; bearProb: number; expectedRangePct: number; confidence: number; source: string };
  structure: { bias: string; support: number | null; resistance: number | null; bos: string | null; breakout: string | null; falseBreakout: string | null };
}
export interface ChartData {
  exchange: string; symbol: string; timeframe: string;
  candles: { time: number; open: number; high: number; low: number; close: number; volume: number }[];
  overlays: Record<'ema9' | 'ema21' | 'vwap' | 'bbUpper' | 'bbLower', { time: number; value: number }[]>;
  analysis: Analysis | null;
}
