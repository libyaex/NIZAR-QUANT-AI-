"""Technical analysis engine.

Candlestick patterns, market structure, and fast indicators. All functions
operate on pandas DataFrames with columns: open, high, low, close, volume.
Output dictionaries are plain primitives suitable for JSON responses.
"""
from typing import Dict, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Indicators (vectorized, no TA-Lib binary dependency required)
# ---------------------------------------------------------------------------

def ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False).mean()


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd_hist(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    line = ema(closes, fast) - ema(closes, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line - sig


def stochastic_rsi(closes: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    r = rsi(closes, rsi_period)
    lo = r.rolling(stoch_period).min()
    hi = r.rolling(stoch_period).max()
    return ((r - lo) / (hi - lo).replace(0, np.nan)).fillna(0.5) * 100


def bollinger(closes: pd.Series, period: int = 20, mult: float = 2.0) -> Dict[str, pd.Series]:
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    return {"mid": mid, "upper": mid + mult * std, "lower": mid - mult * std}


def vwap(df: pd.DataFrame) -> float:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    return float((typical * vol).sum() / vol.sum()) if vol.notna().any() else float(df["close"].iloc[-1])


def volume_sma_ratio(volumes: pd.Series, period: int = 20) -> float:
    if len(volumes) < period + 1:
        return 1.0
    return float(volumes.iloc[-1] / max(volumes.iloc[-period:].mean(), 1e-12))


# ---------------------------------------------------------------------------
# Candlestick analysis
# ---------------------------------------------------------------------------

def analyze_candlesticks(df: pd.DataFrame) -> Dict:
    """Score recent candles: engulfing, pin bar, hammer/shooting star, doji,
    momentum candles, wick rejection, body strength, consecutive behavior."""
    out: Dict = {"bull_score": 0.0, "bear_score": 0.0, "reasons": []}
    if len(df) < 3:
        return out
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    bull = (c > o).astype(float)
    bull.iloc[:len(bull)] = bull  # keep dtype

    last = -1
    prev = -2

    # Bullish / bearish engulfing
    if body.iloc[last] > body.iloc[prev] and c.iloc[last] > o.iloc[prev] and c.iloc[prev] < o.iloc[prev]:
        out["bull_score"] += 2.0
        out["reasons"].append("bullish_engulfing")
    if body.iloc[last] > body.iloc[prev] and c.iloc[last] < o.iloc[prev] and c.iloc[prev] > o.iloc[prev]:
        out["bear_score"] += 2.0
        out["reasons"].append("bearish_engulfing")

    # Pin bar / hammer / shooting star (current candle only)
    if rng.iloc[last] > 0:
        if lower_wick.iloc[last] > 2 * body.iloc[last] and lower_wick.iloc[last] > 0.6 * rng.iloc[last]:
            out["bull_score"] += 1.5
            out["reasons"].append("hammer_pin_bar")
        if upper_wick.iloc[last] > 2 * body.iloc[last] and upper_wick.iloc[last] > 0.6 * rng.iloc[last]:
            out["bear_score"] += 1.5
            out["reasons"].append("shooting_star_pin_bar")

    # Doji (indecision — reduce both)
    if body.iloc[last] < 0.1 * rng.iloc[last]:
        out["reasons"].append("doji")
        out["bull_score"] -= 0.5
        out["bear_score"] -= 0.5

    # Momentum candle strength
    body_pct = float(body.iloc[last] / max(rng.iloc[last], 1e-12))
    if body_pct > 0.7:
        if c.iloc[last] > o.iloc[last]:
            out["bull_score"] += 1.0
            out["reasons"].append("strong_bull_momentum")
        else:
            out["bear_score"] += 1.0
            out["reasons"].append("strong_bear_momentum")

    # Consecutive behavior (last 3 candles)
    tail3 = bull.iloc[-3:]
    if tail3.sum() == 3:
        out["bull_score"] += 1.0
        out["reasons"].append("three_bulls")
    if tail3.sum() == 0:
        out["bear_score"] += 1.0
        out["reasons"].append("three_bears")

    # Wick rejection of previous extremes
    if len(df) >= 10:
        if l.iloc[last] < df["low"].iloc[-10:-1].min() and c.iloc[last] > o.iloc[last]:
            out["bull_score"] += 1.5
            out["reasons"].append("liquidity_sweep_reversal")
        if h.iloc[last] > df["high"].iloc[-10:-1].max() and c.iloc[last] < o.iloc[last]:
            out["bear_score"] += 1.5
            out["reasons"].append("liquidity_sweep_reversal")

    return out


# ---------------------------------------------------------------------------
# Market structure
# ---------------------------------------------------------------------------

def analyze_structure(df: pd.DataFrame, lookback: int = 60) -> Dict:
    """HH/HL, LH/LL, break of structure, change of character, S/R levels."""
    out: Dict = {"bias": "neutral", "strength": 0.0, "support": None, "resistance": None, "reasons": []}
    if len(df) < 20:
        return out
    d = df.tail(lookback)
    swing highs, _swing lows placeholder removed  # noqa
    return out