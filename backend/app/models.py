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


class TradingMode(str, Enum):
    paper = "paper"
    live = "live"


class RiskSettings(BaseModel):
    tradingMode: TradingMode = TradingMode.paper
    paperBalance: float = Field(default=100.0, gt=0)
    riskPerTradePct: float = Field(default=1.0, gt=0, le=10)
    maxConcurrentPositions: int = Field(default=3, ge=1, le=20)
    maxDailyLossPct: float = Field(default=5.0, gt=0, le=100)
    maxDrawdownPct: float = Field(default=20.0, gt=0, le=100)
    maxLeverage: int = Field(default=5, ge=1, le=125)
    stopLossPct: float = Field(default=0.35, gt=0, le=20)
    takeProfitPct: float = Field(default=0.6, gt=0, le=50)
    trailingStopPct: float = Field(default=0.2, gt=0, le=20)
    partialTakeProfitPct: float = Field(default=50.0, ge=0, le=100)
    maxHoldingMinutes: int = Field(default=20, ge=1, le=1440)
    consecutiveLossLimit: int = Field(default=4, ge=1, le=50)
    minOpportunityScore: float = Field(default=0.5, ge=0.1, le=1.0)
    takerFeePct: float = Field(default=0.05, ge=0, le=1)


class ScannerConfig(BaseModel):
    maxSymbols: int = Field(default=30, ge=5, le=100)
    minVolumeUsd: float = Field(default=5_000_000, ge=0)
    maxSpreadPct: float = Field(default=0.08, gt=0)
    minAtrPct: float = Field(default=0.04, ge=0)
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
    price: float = 0.0
    change24hPct: float = 0.0
    momentum: float = 0.0
    relativeVolume: float = 1.0
    probSource: str = "heuristic_prior"
    confidence: float = 0.0
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
    protectedOnExchange: bool = False
    mode: str = "paper"
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
    mode: str = "paper"
    equity: float = 0.0
    haltReason: str = ""
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
    daily: List[Dict[str, Any]] = Field(default_factory=list)
    weekly: List[Dict[str, Any]] = Field(default_factory=list)
    curve: List[Dict[str, Any]] = Field(default_factory=list)