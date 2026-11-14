"""Microstructure metrics: spread, order book imbalance, volume delta, CVD."""
import numpy as np
import pandas as pd
from typing import Dict, Optional


def spread_metrics(bid: float, ask: float, mid: Optional[float] = None) -> Dict:
    mid = mid or (bid + ask) / 2
    spread_abs = ask - bid
    return {
        "spread_abs": float(spread_abs),
        "spread_pct": float(spread_abs / mid * 100) if mid else 0.0,
    }


def order_book_imbalance(bids: np.ndarray, asks: np.ndarray, depth: int = 20) -> float:
    """Return imbalance in [-1, 1]. Positive = buy pressure.
    bids/asks: arrays of [price, size]."""
    b = bids[:depth]
    a = asks[:depth]
    bid_vol = float(np.sum(b[:, 1])) if len(b) else 0.0
    ask_vol = float(np.sum(a[:, 1])) if len(a) else 0.0
    total = bid_vol + ask_vol
    if total <= 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def candle_volume_delta(df: pd.DataFrame) -> Dict:
    """Approximate per-candle delta from OHLC shape (no tick data needed):
    close position within the range proxies intrabar buy/sell split."""
    if df.empty:
        return {"delta": 0.0, "cvd": 0.0, "buy_pressure": 0.5}
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    close_pos = ((df["close"] - df["low"]) / rng).fillna(0.5)
    vol = df["volume"].fillna(0)
    delta = (2 * close_pos - 1) * vol
    cvd = float(delta.sum())
    last_delta = float(delta.iloc[-1])
    buy_pressure = float(close_pos.iloc[-1])
    return {"delta": last_delta, "cvd": cvd, "buy_pressure": buy_pressure}


def tick_volume_delta(tick_sizes: np.ndarray, tick_sides: np.ndarray) -> Dict:
    """Exact delta/CVD when aggressor side tick data is available.
    tick_sides: +1 buy, -1 sell."""
    delta = float(np.sum(tick_sizes * tick_sides))
    return {"delta": delta, "cvd": delta}


def price_acceleration(df: pd.DataFrame, window: int = 5) -> float:
    """Second-derivative style acceleration of close price (normalized)."""
    if len(df) < window + 2:
        return 0.0
    closes = df["close"]
    v1 = closes.diff()
    acc = v1.diff()
    if closes.iloc[-1] == 0:
        return 0.0
    return float(acc.tail(window).mean() / closes.iloc[-1] * 100)


def relative_volume(df: pd.DataFrame, period: int = 20) -> float:
    if len(df) < period + 1:
        return 1.0
    v = df["volume"]
    avg = v.iloc[-(period + 1):-1].mean()
    return float(v.iloc[-1] / avg) if avg else 1.0


def momentum_score(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> float:
    """Normalized short-term momentum in [-1, 1]."""
    if len(df) < slow + 1:
        return 0.0
    closes = df["close"]
    f = closes.rolling(fast).mean()
    s = closes.rolling(slow).mean()
    diff = (f - s) / s
    return float(np.clip(diff.iloc[-1] * 20, -1, 1))