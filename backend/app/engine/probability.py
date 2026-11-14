"""Next-candle probability engine.

Estimates bullish/bearish probability and expected movement range for the
next short-term candle using logistic regression over engineered features.
The model is trained online from realized candle outcomes; until enough
samples exist, a transparent heuristic prior is used. Outputs are estimates,
not guarantees.
"""
import time
from collections import deque
from typing import Dict, Optional

import numpy as np

from app.engine import analysis, microstructure


class ProbabilityEngine:
    """Estimates next-candle direction probability.

    Two components:
    1. A transparent heuristic prior from TA features (always available).
    2. An online logistic-regression fit updated with realized outcomes
       (scikit-learn SGDClassifier, warm_start). The blend weight of the
       learned model grows with sample count.
    """

    def __init__(self, max_samples: int = 5000):
        self._buf_x: deque = deque(maxlen=max_samples)
        self._buf_y: deque = deque(maxlen=max_samples)
        self._model = None
        self._last_fit = 0.0
        self._fit_every = 60
        self._samples_seen = 0
        self._classes_seen = set()

    # ------------------------------------------------------------------
    def features(self, df) -> Optional[np.ndarray]:
        """Feature vector for the most recent completed candle. None if insufficient data."""
        if df is None or len(df) < 30:
            return None
        c = df["close"]
        candles = analysis.analyze_candlesticks(df)
        st = analysis.ema(c, 9).iloc[-1] / max(c.iloc[-1], 1e-12) - 1
        r = analysis.rsi(c).iloc[-1]
        mh = analysis.macd_hist(c).iloc[-1]
        srsi = analysis.stochastic_rsi(c).iloc[-1]
        a = analysis.atr(df).iloc[-1]
        atr_pct = a / max(c.iloc[-1], 1e-12)
        mom = microstructure.momentum_score(df)
        rv = microstructure.relative_volume(df)
        acc = microstructure.price_acceleration(df)
        vd = microstructure.candle_volume_delta(df)
        ret1 = float(c.pct_change().iloc[-1] or 0.0)
        ret3 = float(c.iloc[-1] / c.iloc[-3] - 1) if len(c) >= 3 else 0.0
        return np.array([
            st, (r - 50) / 50, mh * 10, (srsi - 50) / 50, atr_pct * 100,
            mom, rv, acc, vd["buy_pressure"] - 0.5,
            candles["bull_score"] - candles["bear_score"],
            ret1 * 100, ret3 * 100,
        ], dtype=float)

    # ------------------------------------------------------------------
    @staticmethod
    def _prior(x: np.ndarray) -> float:
        """Heuristic prior probability of bullish next candle in (0,1)."""
        # features: ema9 offset, rsi norm, macd hist, stoch rsi norm, atr pct,
        # momentum, rel volume, accel, buy pressure, candle score, ret1, ret3
        score = 0.0
        score += np.clip(x[0] * 30, -1, 1) * 1.0
        score += np.clip(x[1], -1, 1) * 0.8
        score += np.clip(x[2], -1, 1) * 0.8
        score += np.clip(x[3], -1, 1) * 0.6
        score += np.clip(x[5], -1, 1) * 1.2
        score += np.clip(x[7] * 10, -1, 1) * 0.6
        score += np.clip(x[8] * 4, -1, 1) * 0.8
        score += np.clip(x[9] / 4, -1, 1) * 1.5
        score += np.clip(x[10] * 10, -1, 1) * 0.8
        score += np.clip(x[11] * 10, -1, 1) * 0.5
        return 1.0 / (1.0 + np.exp(-score))

    # ------------------------------------------------------------------
    def predict(self, df) -> Dict:
        """Return probabilities and expected range estimate for next candle."""
        x = self.features(df)
        if x is None:
            return {"bullProb": 0.5, "bearProb": 0.5, "expectedRangePct": 0.0,
                    "confidence": 0.0, "source": "insufficient_data"}

        prior = self._prior(x)
        prob = prior
        source = "heuristic_prior"
        conf = 0.3

        if self._model is not None and len(self._classes_seen) > 1 and len(self._buf_y) >= 200:
            try:
                p = float(self._model.predict_proba(x.reshape(1, -1))[0][1])
                w = min(0.8, (len(self._buf_y) - 200) / 1000 * 0.8)
                prob = (1 - w) * prior + w * p
                source = "blended_model"
                conf = 0.3 + 0.4 * w
            except Exception:
                pass

        a = analysis.atr(df).iloc[-1]
        close = df["close"].iloc[-1]
        expected_range_pct = float(a / max(close, 1e-12) * 100) if close else 0.0
        bull = float(np.clip(prob, 0.0, 1.0))
        return {
            "bullProb": bull,
            "bearProb": 1.0 - bull,
            "expectedRangePct": expected_range_pct,
            "confidence": float(np.clip(conf * (0.5 + 0.5 * abs(2 * bull - 1)), 0, 1)),
            "source": source,
        }

    # ------------------------------------------------------------------
    def record_outcome(self, df, next_close: float) -> None:
        """Feed the online model with a realized outcome (label: bullish or not)."""
        x = self.features(df)
        if x is None:
            return
        y = 1 if next_close >= df["close"].iloc[-1] else 0
        self._buf_x.append(x)
        self._buf_y.append(y)
        self._classes_seen.add(y)
        self._samples_seen += 1
        if time.time() - self._last_fit > self._fit_every and len(self._classes_seen) > 1 and len(self._buf_y) >= 50:
            self._refit()

    def _refit(self) -> None:
        try:
            from sklearn.linear_model import SGDClassifier
        except ImportError:
            return
        X = np.array(self._buf_x)
        y = np.array(self._buf_y)
        if self._model is None:
            self._model = SGDClassifier(loss="log_loss", alpha=1e-4, random_state=42, warm_start=True)
            self._model.partial_fit(X, y, classes=np.array([0, 1]))
        else:
            self._model.partial_fit(X, y)
        self._last_fit = time.time()