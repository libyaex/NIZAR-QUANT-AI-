"""Unified signal/decision engine.

Combines candlestick analysis, market structure, multi-timeframe direction,
momentum, volume, volatility, liquidity, order-flow, next-candle probability,
trading costs, and risk conditions into a single decision with an
opportunity score. HOLD is emitted when conditions are unsuitable.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from app.engine import analysis, microstructure, structure
from app.engine.probability import ProbabilityEngine
from app.models import Opportunity, TradingDecision


class DecisionEngine:
    def __init__(self, probability: ProbabilityEngine, min_score: float = 0.55):
        self.probability = probability
        self.min_score = min_score

    # ------------------------------------------------------------------
    def evaluate(
        self,
        exchange: str,
        symbol: str,
        product: str,
        dfs: Dict[str, "object"],
        book: Optional[Dict] = None,
        taker_fee_pct: float = 0.05,
        min_score_override: Optional[float] = None,
    ) -> Optional[Opportunity]:
        """dfs maps timeframe -> DataFrame. Primary timeframe key '1m' required."""
        primary = dfs.get("1m")
        if primary is None or len(primary) < 30:
            return None

        c = primary["close"]
        price = float(c.iloc[-1])

        # --- component scores -------------------------------------------------
        candles = analysis.analyze_candlesticks(primary)
        struct = structure.analyze_structure(primary)
        br = structure.breakout_status(primary, struct["support"], struct["resistance"])

        ema9 = analysis.ema(c, 9)
        ema21 = analysis.ema(c, 21)
        trend_bias = 0.0
        if ema9.iloc[-1] > ema21.iloc[-1]:
            trend_bias += 0.5
        else:
            trend_bias -= 0.5

        r = analysis.rsi(c).iloc[-1]
        mh = analysis.macd_hist(c).iloc[-1]
        srsi = analysis.stochastic_rsi(c).iloc[-1]
        a = analysis.atr(primary).iloc[-1]
        atr_pct = a / price * 100 if price else 0.0
        bb = analysis.bollinger(c)
        bb_pos = 0.0
        bb_range = bb["upper"].iloc[-1] - bb["lower"].iloc[-1]
        if bb_range:
            bb_pos = (price - bb["lower"].iloc[-1]) / bb_range

        mom = microstructure.momentum_score(primary)
        rel_vol = microstructure.relative_volume(primary)
        accel = microstructure.price_acceleration(primary)
        vd = microstructure.candle_volume_delta(primary)

        imbalance = 0.0
        spread_pct = 0.0
        if book is not None:
            sp = microstructure.spread_metrics(book.get("bid", price * 0.999), book.get("ask", price * 1.001))
            spread_pct = sp["spread_pct"]
            imbalance = microstructure.order_book_imbalance(
                np.array(book.get("bids", []), dtype=float).reshape(-1, 2) if len(book.get("bids", [])) else np.zeros((1, 2)),
                np.array(book.get("asks", []), dtype=float).reshape(-1, 2) if len(book.get("asks", [])) else np.zeros((1, 2)),
            )

        prob = self.probability.predict(primary)

        # --- multi-timeframe confirmation --------------------------------------
        mtf_bias = 0.0
        for tf in ("3m", "5m", "15m"):
            dfc = dfs.get(tf)
            if dfc is None or len(dfc) < 30:
                continue
            cc = dfc["close"]
            e_fast = analysis.ema(cc, 9).iloc[-1]
            e_slow = analysis.ema(cc, 21).iloc[-1]
            mtf_bias += 0.25 if e_fast > e_slow else -0.25

        # --- direction aggregation ---------------------------------------------
        bull = 0.0
        bear = 0.0
        bull += candles["bull_score"] * 0.08
        bear += candles["bear_score"] * 0.08
        bull += max(struct.get("strength", 0), 0) * (0.4 if struct["bias"] == "bullish" else 0)
        bear += max(struct.get("strength", 0), 0) * (0.4 if struct["bias"] == "bearish" else 0)
        bull += trend_bias > 0 and 0.25 or 0.0
        bear += trend_bias < 0 and 0.25 or 0.0
        bull += (mtf_bias > 0) * min(abs(mtf_bias), 1) * 0.2
        bear += (mtf_bias < 0) * min(abs(mtf_bias), 1) * 0.2
        bull += np.clip((r - 50) / 50, -1, 1) * 0.15 if r > 55 else 0
        bear += np.clip((50 - r) / 50, -1,  engine_placeholder := 1) * 0.15 if r < 45 else 0
        bull += (mh > 0) * 0.15
        bear += (mh < 0) * 0.15
        bull += (srsi < 30) * 0.1
        bear += (srsi > 70) * 0.1
        bull += (bb_pos < 0.2) * 0.1
        bear += (bb_pos > 0.8) * 0.1
        bull += max(mom, 0) * 0.25
        bear += max(-mom, 0) * 0.25
        bull += max(accel, 0) * 0.15
        bear += max(-accel, 0) * 0.15
        bull += max(imbalance, 0) * 0.2
        bear += max(-imbalance, 0) * 0.2
        bull += max(vd["buy_pressure"] - 0.5, 0) * 0.3
        bear += max(0.5 - vd["buy_pressure"], 0) * 0.3
        bull += (prob["bullProb"] - 0.5) * 1.2
        bear += (0.5 - prob["bullProb"]) * 1.2

        if br.get("breakout") and str(br["breakout"]).startswith("bullish"):
            bull += 0.25
        if br.get("breakout") and str(br["breakout"]).startswith("bearish"):
            bear += 0.25
        if br.get("false_breakout") == "bullish":
            bear += 0.2
        if br.get("false_breakout") == "bearish":
            bull += 0.2

        raw = bull - bear
        # liquidity and tradability gates
        if spread_pct > 0.08 or atr_pct < 0.05 or rel_vol < 0.6:
            return None

        # expected move vs cost: round trip taker fees
        cost_pct = taker_fee_pct * 2 + spread_pct
        exp_move = prob.get("expectedRangePct", 0.0) * 0.5
        if exp_move < cost_pct * 1.5:
            return None

        direction = TradingDecision.LONG if raw > 0 else TradingDecision.SHORT
        score = float(min(abs(raw), 1.5) / 1.5)
        score *= 0.6 + 0.4 * prob.get("confidence", 0)
        threshold = min_score_override or self.min_score
        if score < threshold:
            return None

        reasons: List[str] = list(candles.get("reasons", [])) + list(struct.get("reasons", [])) + br.get("reasons", [])
        return Opportunity(
            symbol=symbol,
            exchange=exchange,
            product=product,
            score=round(score, 3),
            decision=direction,
            bullProb=round(prob["bullProb"], 4),
            bearProb=round(prob["bearProb"], 4),
            expectedRangePct=round(exp_move, 4),
            spreadPct=round(spread_pct, 4),
            volumeUsd=round(float(primary["volume"].tail(5).sum() * price), 0),
            atrPct=round(atr_pct, 4),
            reasons=sorted(set(reasons))[:8],
            ts=datetime.now(timezone.utc),
        )