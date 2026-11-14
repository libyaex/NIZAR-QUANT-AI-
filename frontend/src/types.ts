export type TradingState = 'engine_ready' | 'trading_active' | 'trading_stopped' | 'connection_lost' | 'emergency_halt';

export interface EngineStatus {
  state: TradingState;
  uptimeSeconds: number;
  exchangesConnected: string[];
  scannedSymbols: number;
  openPositions: number;
  tradingActive: boolean;
  message: string;
}

export interface Opportunity {
  symbol: string;
  exchange: string;
  product: string;
  score: number;
  decision: 'LONG' | 'SHORT' | 'HOLD';
  bullProb: number;
  bearProb: number;
  expectedRangePct: number;
  spreadPct: number;
  volumeUsd: number;
  atrPct: number;
  reasons: string[];
  ts: string;
}

export interface Position {
  positionId: string;
  exchange: string;
  symbol: string;
  product: string;
  side: 'long' | 'short';
  qty: number;
  entryPrice: number;
  markPrice: number;
  leverage: number;
  stopLoss: number | null;
  takeProfit: number | null;
  trailingActive: boolean;
  partialFilled: boolean;
  realizedPnl: number;
  unrealizedPnl: number;
  openedAt: string;
  updatedAt: string;
}

export interface RiskSettings {
  riskPerTradePct: number;
  maxConcurrentPositions: number;
  maxDailyLossPct: number;
  maxDrawdownPct: number;
  maxLeverage: number;
  stopLossPct: number;
  takeProfitPct: number;
  trailingStopPct: number;
  partialTakeProfitPct: number;
  maxHoldingMinutes: number;
  consecutiveLossLimit: number;
  minOpportunityScore: number;
}

export interface ScannerConfig {
  maxSymbols: number;
  minVolumeUsd: number;
  maxSpreadPct: number;
  minAtrPct: number;
  primaryTimeframe: string;
  confirmationTimeframes: string[];
}

export interface Mission {
  id: string;
  startingCapital: number;
  currentCapital: number;
  targetCapital: number;
  realizedProfit: number;
  unrealizedProfit: number;
  remaining: number;
  progressPct: number;
  status: 'active' | 'paused' | 'completed';
  compounding: boolean;
  startedAt: string | null;
  completedAt: string | null;
  allowsNewTrades: boolean;
}

export interface ExchangeStatus {
  id: string;
  exchange: string;
  label: string;
  product: string;
  testnet: boolean;
  connected: boolean;
  markets: number;
  lastError: string | null;
  createdAt: string | null;
}

export interface Performance {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  netPnl: number;
  totalFees: number;
  avgProfit: number;
  avgLoss: number;
  profitFactor: number;
  maxDrawdown: number;
  todayPnl: number;
  weekPnl: number;
  spot: { trades: number; netPnl: number; winRate: number } | null;
  futures: { trades: number; netPnl: number; winRate: number } | null;
}

export interface TradeRecord {
  id: string;
  exchange: string;
  symbol: string;
  product: string;
  side: 'long' | 'short';
  qty: number;
  entry_price: number;
  exit_price: number | null;
  realized_pnl: number;
  fees: number;
  status: string;
  created_at: string;
  closed_at: string | null;
}
