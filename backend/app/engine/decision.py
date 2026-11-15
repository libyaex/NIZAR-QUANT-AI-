"""Unified signal / decision engine.

Every analysis block is normalised to a score in [-1, 1] (positive = bullish).
The blocks are combined with fixed weights into one ``edge``; the decision is
LONG / SHORT only when the edge is strong enough, several independent blocks
agree, higher timeframes do not strongly disagree, and the market is tradable
after costs. Anything else is HOLD with the reason, so the scanner can show
*why* a market was rejected instead of silently dropping it.
"""
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from app.engine import analysis, microstructure, structure
from app.engine.candles import resample_ohlcv
from app.engine.probability import ProbabilityEngine
from app.models import Opportunity, TradingDecision

WEIGHTS = {
    "candles": 0.12, "structure": 0.16, "trend": 0.10, "mtf": 0.16,
    "momentum": 0.10, "oscillators": 0.10, "orderflow": 0.12, "probability": 0.14,
}


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


class DecisionEngine:
    def __init__(self, probability: ProbabilityEngine):
        self.probability = probability

    # ------------------------------------------------------------------
    def analyze(self, dfs: Dict[str, Any], book: Optional[Dict] = None, taker_fee_pct: float = 0.05,
                max_spread_pct: float = 0.08, min_atr_pct: float = 0.04,
                min_score: float = 0.5) -> Optional[Dict[str, Any]]:
        primary = dfs.get("1m")
        if primary is None or len(primary) < 40:
            return None
        c = primary["close"]
        price = float(c.iloc[-1])
        if price <= 0:
            return None

        candles = analysis.analyze_candlesticks(primary)
        struct = structure.analyze_structure(primary)
        br = structure.breakout_status(primary, struct["support"], struct["resistance"])
        atr_val = float(analysis.atr(primary).iloc[-1])
        atr_pct = atr_val / price * 100
        ema9, ema21 = analysis.ema(c, 9), analysis.ema(c, 21)
        rsi = float(analysis.rsi(c).iloc[-1])
        macd = float(analysis.macd_hist(c).iloc[-1])
        srsi = float(analysis.stochastic_rsi(c).iloc[-1])
        bb = analysis.bollinger(c)
        bb_rng = float(bb["upper"].iloc[-1] - bb["lower"].iloc[-1])
        bb_pos = float((price - bb["lower"].iloc[-1]) / bb_rng) if bb_rng else 0.5
        vwap = analysis.vwap(primary.tail(60))
        mom = microstructure.momentum_score(primary)
        accel = microstructure.price_acceleration(primary)
        rel_vol = microstructure.relative_volume(primary)
        vd = microstructure.candle_volume_delta(primary.tail(30))

        imbalance, spread_pct = 0.0, 0.0
        if book:
            bids = np.array(book.get("bids") or [], dtype=float)
            asks = np.array(book.get("asks") or [], dtype=float)
            bid = book.get("bid") or (float(bids[0][0]) if len(bids) else price)
            ask = book.get("ask") or (float(asks[0][0]) if len(asks) else price)
            spread_pct = microstructure.spread_metrics(bid, ask)["spread_pct"]
            if bids.ndim == 2 and asks.ndim == 2 and bids.shape[1] >= 2 and asks.shape[1] >= 2:
                imbalance = microstructure.order_book_imbalance(bids[:, :2], asks[:, :2])

        prob = self.probability.predict(primary)

        # --- multi-timeframe direction (3m/5m/15m); fall back to resampled 1m
        mtf_votes: List[float] = []
        for tf, minutes in (("3m", 3), ("5m", 5), ("15m", 15)):
            d = dfs.get(tf)
            if d is None or len(d) < 25:
                d = resample_ohlcv(primary, minutes)
            if d is None or len(d) < 25:
                continue
            cc = d["close"]
            gap = float(analysis.ema(cc, 9).iloc[-1] - analysis.ema(cc, 21).iloc[-1])
            mtf_votes.append(_clip(gap / price * 100 / max(atr_pct * 0.6, 1e-6)))
        mtf = float(np.mean(mtf_votes)) if mtf_votes else 0.0

        # --- block scores in [-1, 1]
        s_candles = _clip((candles["bull_score"] - candles["bear_score"]) / 4)
        s_struct = 0.0
        if struct["bias"] == "bullish":
            s_struct += 0.6 * struct.get("strength", 1.0)
        elif struct["bias"] == "bearish":
            s_struct -= 0.6 * struct.get("strength", 1.0)
        if struct.get("bos") == "bullish":
            s_struct += 0.3
        elif struct.get("bos") == "bearish":
            s_struct -= 0.3
        bo = str(br.get("breakout") or "")
        s_struct += 0.3 if bo.startswith("bullish") else -0.3 if bo.startswith("bearish") else 0.0
        s_struct += -0.4 if br.get("false_breakout") == "bullish" else 0.4 if br.get("false_breakout") == "bearish" else 0.0
        s_struct = _clip(s_struct)
        gap1 = float(ema9.iloc[-1] - ema21.iloc[-1])
        s_trend = _clip(gap1 / price * 100 / max(atr_pct * 0.6, 1e-6))
        s_mom = _clip(0.7 * mom + 0.3 * _clip(accel * 20))
        s_osc = _clip(0.5 * _clip((rsi - 50) / 20) + 0.5 * _clip(macd / max(atr_val * 0.1, 1e-12)))
        s_flow = _clip(0.5 * imbalance + 0.5 * _clip((vd["buy_pressure"] - 0.5) * 3))
        s_prob = _clip((prob["bullProb"] - 0.5) * 5)
        comps = {"candles": s_candles, "structure": s_struct, "trend": s_trend, "mtf": _clip(mtf),
                 "momentum": s_mom, "oscillators": s_osc, "orderflow": s_flow, "probability": s_prob}
        edge = float(sum(WEIGHTS[k] * v for k, v in comps.items()))
        direction = TradingDecision.LONG if edge > 0 else TradingDecision.SHORT
        sign = 1 if edge > 0 else -1
        agree = sum(1 for v in comps.values() if v * sign > 0.15)

        reasons: List[str] = list(candles.get("reasons", [])) + list(struct.get("reasons", [])) + list(br.get("reasons", []))
        reject: Optional[str] = None
        cost_pct = taker_fee_pct * 2 + spread_pct
        if spread_pct > max_spread_pct:
            reject = f"spread {spread_pct:.3f}% too wide"
        elif atr_pct < min_atr_pct:
            reject = f"volatility {atr_pct:.3f}% too low"
        elif rel_vol < 0.5:
            reject = "volume drying up"
        elif atr_pct * math.sqrt(10) < cost_pct * 1.5:
            reject = "expected move does not cover costs"
        elif comps["mtf"] * sign < -0.6:
            reject = "higher timeframes disagree"
        elif agree < 5:
            reject = f"weak agreement ({agree}/8 blocks)"

        # exhaustion: do not chase an already stretched move
        exhausted = (sign > 0 and (rsi > 78 or bb_pos > 1.0)) or (sign < 0 and (rsi < 22 or bb_pos < 0.0))
        score = _clip(abs(edge) / 0.6, 0, 1) * (0.7 + 0.3 * agree / 8)
        if exhausted:
            score *= 0.7
            reasons.append("stretched_move")
        if reject is None and score < min_score:
            reject = f"score {score:.2f} below threshold"
        decision = TradingDecision.HOLD if reject else direction
        if reject:
            reasons.append(reject)

        return {
            "decision": decision, "direction": direction, "score": float(score), "edge": edge,
            "components": comps, "agree": agree, "reasons": reasons[:10], "reject": reject,
            "price": price, "atrPct": atr_pct, "spreadPct": spread_pct, "imbalance": imbalance,
            "relVolume": rel_vol, "momentum": mom, "rsi": rsi, "macdHist": macd, "stochRsi": srsi,
            "bbPos": bb_pos, "vwap": vwap, "prob": prob,
            "structure": {"bias": struct["bias"], "support": struct["support"], "resistance": struct["resistance"],
                          "bos": struct.get("bos"), "breakout": br.get("breakout"),
                          "falseBreakout": br.get("false_breakout")},
            "costPct": cost_pct,
        }

    # ------------------------------------------------------------------
    def evaluate(self, exchange: str, symbol: str, product: str, dfs: Dict[str, Any],
                 book: Optional[Dict] = None, taker_fee_pct: float = 0.05,
                 max_spread_pct: float = 0.08, min_atr_pct: float = 0.04, min_score: float = 0.5,
                 meta: Optional[Dict[str, float]] = None) -> Optional[Opportunity]:
        a = self.analyze(dfs, book, taker_fee_pct, max_spread_pct, min_atr_pct, min_score)
        if a is None:
            return None
        meta = meta or {}
        return Opportunity(
            symbol=symbol, exchange=exchange, product=product,
            score=round(a["score"], 3), decision=a["decision"],
            price=a["price"], change24hPct=round(float(meta.get("change24hPct", 0.0)), 2),
            momentum=round(a["momentum"], 3), relativeVolume=round(a["relVolume"], 2),
            probSource=a["prob"].get("source", "heuristic_prior"),
            confidence=round(float(a["prob"].get("confidence", 0.0)), 3),
            bullProb=round(a["prob"]["bullProb"], 4), bearProb=round(a["prob"]["bearProb"], 4),
            expectedRangePct=round(a["atrPct"], 4), spreadPct=round(a["spreadPct"], 4),
            volumeUsd=round(float(meta.get("volume24hUsd", 0.0)), 0), atrPct=round(a["atrPct"], 4),
            reasons=a["reasons"][:8], ts=datetime.now(timezone.utc),
        )
