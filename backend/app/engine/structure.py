"""Market structure analysis: swings, BOS/CHoCH, support/resistance."""
import numpy as np
import pandas as pd
from typing import Dict, Tuple


def _swings(df: pd.DataFrame, width: int = 3) -> Tuple[np.ndarray, np.ndarray]:
    """Return (swing_high_idx, swing_low_idx) simple fractal pivots."""
    highs = df["high"].values
    lows = df["low"].values
    hi_idx = []
    lo_idx = []
    for i in range(width, len(highs) - width):
        window_hi = highs[i - width:i + width + 1]
        window_lo = lows[i - width:i + width + 1]
        if highs[i] == window_hi.max() and (window_hi.argmax() == width):
            hi_idx.append(i)
        if lows[i] == window_lo.min() and (window_lo.argmin() == width):
            lo_idx.append(i)
    return np.array(hi_idx), np.array(lo_idx)


def analyze_structure(df: pd.DataFrame, lookback: int = 60, width: int = 3) -> Dict:
    """HH/HL, LH/LL trend bias, break of structure, change of character,
    nearest support/resistance from swing pivots."""
    out: Dict = {
        "bias": "neutral", "strength": 0.0,
        "support": None, "resistance": None,
        "bos": None, "choch": None, "reasons": [],
    }
    if len(df) < 2 * width + 8:
        return out
    d = df.tail(lookback).reset_index(drop=True)
    hi_idx, lo_idx = _swings(d, width)
    if len(hi_idx) < 2 or len(lo_idx) < 2:
        # fallback S/R from rolling extremes
        out["support"] = float(d["low"].tail(20).min())
        out["resistance"] = float(d["high"].tail(20).max())
        return out

    last2_hi = [d["high"].iloc[i] for i in hi_idx[-2:]]
    last2_lo = [d["low"].iloc[i] for i in lo_idx[-2:]]

    hh = last2_hi[1] > last2_hi[0]
    hl = last2_lo[1] > last2_lo[0]
    lh = last2_hi[1] < last2_hi[0]
    ll = last2_lo[1] < last2_lo[0]

    if hh and hl:
        out["bias"] = "bullish"
        out["strength"] = 1.0
        out["reasons"].append("hh_hl_uptrend")
    elif lh and ll:
        out["bias"] = "bearish"
        out["strength"] = 1.0
        out["reasons"].append("lh_ll_downtrend")
    else:
        out["bias"] = "ranging"
        out["strength"] = 0.4

    # Break of structure / change of character
    close_last = float(d["close"].iloc[-1])
    if out["bias"] != "bearish" and close_last > max(last2_hi):
        out["bos"] = "bullish"
        out["reasons"].append("bos_bullish")
    if out["bias"] != "bullish" and close_last < min(last2_lo):
        out["bos"] = "bearish"
        out["reasons"].append("bos_bearish")

    prev_bias_window = d.tail(20)
    rising = prev_bias_window["close"].iloc[-1] > prev_bias_window["close"].iloc[0]
    if out["bias"] == "bearish" and rising:
        out["choch"] = "bearish_from_bull"
        out["reasons"].append("choch_bearish")
    if out["bias"] == "bullish" and not rising:
        out["choch"] = "bullish_from_bear"
        out["reasons"].append("choch_bullish")

    out["support"] = float(min(last2_lo))
    out["resistance"] = float(max(last2_hi))
    return out


def breakout_status(df: pd.DataFrame, support: float, resistance: float) -> Dict:
    """Detect breakout vs false breakout against given S/R levels."""
    out: Dict = {"breakout": None, "false_breakout": None, "reasons": []}
    if support is None or resistance is None or len(df) < 3:
        return out
    h, l, c = df["high"].iloc[-1], df["low"].iloc[-1], df["close"].iloc[-1]
    prev_c = df["close"].iloc[-2]
    if c > resistance and h > resistance:
        if prev_c <= resistance:
            out["breakout"] = "bullish"
            out["reasons"].append("resistance_breakout")
        else:
            out["breakout"] = "bullish_confirmed"
    if c < support and l < support:
        if prev_c >= support:
            out["breakout"] = "bearish"
            out["reasons"].append("support_breakdown")
        else:
            out["breakout"] = "bearish_confirmed"
    # false breakout: wick beyond level but close back inside
    if h > resistance and c < resistance:
        out["false_breakout"] = "bullish"
        out["reasons"].append("false_breakout_above")
    if l < support and c > support:
        out["false_breakout"] = "bearish"
        out["reasons"].append("false_breakout_below")
    return out