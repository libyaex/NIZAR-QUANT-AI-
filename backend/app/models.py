"""Pydantic models shared across the backend."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExchangeID(str, Enum):
    binance = "binance"
    mexc = "mexc"
    bybit = "bybit"
    okx = "okx"
    bitget = "bitget"


class ProductType(str, Enum):
    spot = "spot"
    futures = "futures"


class OrderSide(str, Enum):
    long = "long"
    short = "short"


class TradingState(str, Enum):
    engine_ready = "engine_ready"
    trading_active = "trading_active"
    trading_stopped = "trading_stopped"
    connection_lost = "connection_lost"
    emergency_halt = "emergency_halt"


class ExchangeConfigIn(BaseModel):
    exchange: ExchangeID
    label: str = "default"
    apiKey: str
    secret: str
    password: Optional[str] = None
    product: ProductType = ProductType.futures
    testnet: bool = False


class ExchangeStatus(BaseModel):
    id: str
    exchange: str
    label: str
    product: str
    testnet: bool
    connected: bool
    markets: int = 0
    lastError: Optional[str] = None
    createdAt: Optional[datetime] = None


class ExchangeSecretOut(BaseModel):
    apiKeyMasked: str
    hasPassword: bool


class RiskSettings(BaseModel):
    riskPerTradePct: float = 1.0
    maxConcurrentPositions: int = 3
    maxDailyLossPct: float = 5.0
    maxDrawdownPct: float = 20.0
    maxLeverage: int = 10
    stopLossPct: float = 0.4
    takeProfitPct: float = 0.8
    trailingStopPct: float = 0.25
    partialTakeProfitPct: float = 50.0
    maxHoldingMinutes: int = 30
    consecutiveLossLimit: int = 4
    minOpportunityScore: float = 0.55


class ScannerConfig(BaseModel):
    maxSymbols: int = 40
    minVolumeUsd: float = 5_000_000
    maxSpreadPct: float = 0.08
    minAtrPct: float = 0.15
    primaryTimeframe: str = "1m"
    confirmationTimeframes: List[str] = Field(default_factory=lambda: ["3m", "5m", "15m"])


class MissionIn(BaseModel):
    startingCapital: float
    targetCapital: float
    compounding: bool = True
    riskSettings: Optional[RiskSettings] = None


class MissionUpdate(BaseModel):
    status: Optional[str] = None  # active | paused | completed
    compounding: Optional[bool] = None


class TradingDecision(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"


class Opportunity(BaseModel):
    symbol: str
    exchange: str
    product: str
    score: float
    decision: TradingDecision
    bullProb: float
    bearProb: float
    expectedRangePct: float
    spreadPct: float
    volumeUsd: float
    atrPct: float
    reasons: List[str] = Field(default_factory=list)
    ts: datetime


class PositionSnapshot(BaseModel):
    positionId: str
    exchange: str
    symbol: str
    product: str
    side: OrderSide
    qty: float
    entryPrice: float
    markPrice: float
    leverage: int
    stopLoss: Optional[float] = None
    takeProfit: Optional[float] = None
    trailingActive: bool = False
    partialFilled: bool = False
    realizedPnl: float = 0.0
    unrealizedPnl: float = 0.0
    openedAt: datetime
    updatedAt: datetime


class EngineStatusOut(BaseModel):
    state: TradingState
    uptimeSeconds: int
    exchangesConnected: List[str] = Field(default_factory=list)
    scannedSymbols: int = 0
    openPositions: int = 0
    tradingActive: bool = False
    message: str = ""


class StartStopIn(BaseModel):
    action: str  # "start" | "stop" | "halt"


class TradeRecordOut(BaseModel):
    id: str
    exchange: str
    symbol: str
    product: str
    side: OrderSide
    qty: float
    entryPrice: float
    exitPrice: Optional[float]
    realizedPnl: float
    fees: float
    openedAt: datetime
    closedAt: Optional[datetime]
    status: str
    notes: Optional[str] = None


class PerformanceOut(BaseModel):
    totalTrades: int
    wins: int
    losses: int
    winRate: float
    netPnl: float
    totalFees: float
    avgProfit: float
    avgLoss: float
    profitFactor: float
    maxDrawdown: float
    todayPnl: float
    weekPnl: float
    spot: Optional[Dict[str, Any]] = None
    futures: Optional[Dict[str, Any]] = None