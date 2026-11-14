"""Async candle aggregation and indicator computation.

Maintains rolling OHLCV candles per (exchange, symbol, timeframe) built from
WebSocket ticks / REST fetches. Indicators are computed with NumPy/Pandas
without external binary dependencies (TA-Lib optional).
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class Candle:
    ts: int  # open time ms
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {"ts": self.ts, "open": self.open, "high": self.high,
                "low": self.low, "close": self.close, "volume": self.volume}


@dataclass
class CandleSeries:
    """Rolling candle buffer for one (exchange, symbol, timeframe)."""
    exchange: str
    symbol: str
    timeframe: str
    max_candles: int = 300
    candles: List[Candle] = field(default_factory=list)
    last_update: float = 0.0

    def upsert(self, c: Candle) -> None:
        if self.candles and self.candles[-1].ts == c.ts:
            self.candles[-1] = c
        else:
            self.candles.append(c)
            if len(self.candles) > self.max_candles:
                self.candles = self.candles[-self.max_candles:]
        self.last_update = time.time()

    def as_df(self) -> pd.DataFrame:
        if not self.candles:
            return pd.DataFrame()
        return pd.DataFrame([c.to_dict() for c in self.candles])

    def last(self) -> Optional[Candle]:
        return self.candles[-1] if self.candles else None


class CandleManager:
    def __init__(self, timeframe_seconds: Dict[str, int] = None):
        self.series: Dict[Tuple[str, str, str], CandleSeries] = {}
        self.tf_seconds = timeframe_seconds or {
            "1m": 60, "2m": 120, "3m": 180, "5m": 300, "15m": 900
        }
        self._locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}

    def _lock(self, key: Tuple[str, str, str]) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def update_from_trade(self, exchange: str, symbol: str, price: float, size: float, ts_ms: int = None) -> None:
        """Aggregate a tick into each registered timeframe for the symbol."""
        ts_ms = int(ts_ms or time.time() * 1000)
        for tf, sec in self.tf_seconds.items():
            bucket = (ts_ms // (sec * 1000)) * sec * 1000
            key = (exchange, symbol, tf)
            series = self.series.get(key)
            if series is None:
                continue
            async with self._lock(key):
                last = series.last()
                if last is None or last.ts < bucket:
                    series.upsert(Candle(ts=bucket, open=price, high=price, low=price, close=price, volume=size))
                else:
                    last.high = max(last.high, price)
                    last.low = min(last.low, price)
                    last.close = price
                    last.volume += size
                    series.last_update = time.time()

    def seed_from_rest(self, exchange: str, symbol: str, timeframe: str, ohlcv: List[list]) -> None:
        key = (exchange, symbol, timeframe)
        series = self.series.get(key)
        if series is None:
            series = CandleSeries(exchange=exchange, symbol=symbol, timeframe=timeframe)
            self.series[key] = series
        for row in ohlcv:
            if not row or len(row) < 6:
                continue
            c = Candle(ts=int(row[0]), open=float(row[1]), high=float(row[2]),
                       low=float(row[3]), close=float(row[4]), volume=float(row[5]))
            series.upsert(c)

    def get_df(self, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame:
        series = self.series.get((exchange, symbol, timeframe))
        return series.as_df() if series else pd.DataFrame()

    def get_series(self, exchange: str, symbol: str, timeframe: str) -> Optional[CandleSeries]:
        return self.series.get((exchange, symbol, timeframe))

    def ensure_series(self, exchange: str, symbol: str, timeframe: str, max_candles: int = 300) -> CandleSeries:
        key = (exchange, symbol, timeframe)
        if key not in self.series:
            self.series[key] = CandleSeries(exchange=exchange, symbol=symbol,
                                            timeframe=timeframe, max_candles=max_candles)
        return self.series[key]

    def stale_series(self, older_than_seconds: float = 120) -> List[Tuple[str, str, str]]:
        now = time.time()
        return [k for k, s in self.series.items() if now - s.last_update > older_than_seconds]