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
        """Replace the series with a fresh REST snapshot (ordered, de-duplicated)."""
        rows = {}
        for row in ohlcv:
            if row and len(row) >= 6 and row[4] is not None:
                rows[int(row[0])] = Candle(ts=int(row[0]), open=float(row[1]), high=float(row[2]),
                                           low=float(row[3]), close=float(row[4]), volume=float(row[5] or 0))
        series = self.ensure_series(exchange, symbol, timeframe)
        series.candles = [rows[k] for k in sorted(rows)][-series.max_candles:]
        series.last_update = time.time()

    def apply_tick(self, exchange: str, symbol: str, price: float, ts_ms: int) -> None:
        """Synchronous tick update (event-loop single-threaded, so lock-free).
        Only price is applied; tick sizes use exchange-specific units and would
        corrupt the REST-derived volume."""
        for tf, sec in self.tf_seconds.items():
            series = self.series.get((exchange, symbol, tf))
            if series is None or not series.candles:
                continue
            bucket = (ts_ms // (sec * 1000)) * sec * 1000
            last = series.candles[-1]
            if bucket > last.ts:
                series.candles.append(Candle(ts=bucket, open=price, high=price, low=price, close=price, volume=0.0))
                if len(series.candles) > series.max_candles:
                    series.candles = series.candles[-series.max_candles:]
            elif bucket == last.ts:
                last.high = max(last.high, price)
                last.low = min(last.low, price)
                last.close = price
            series.last_update = time.time()

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

def resample_ohlcv(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate 1m candles into N-minute candles (used for 2m/3m and as a
    fallback when a confirmation timeframe was not fetched separately)."""
    if df is None or df.empty or minutes <= 1:
        return df
    ms = minutes * 60_000
    g = df.assign(bucket=(df["ts"] // ms) * ms).groupby("bucket", sort=True)
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum")).reset_index()
    return out.rename(columns={"bucket": "ts"})
