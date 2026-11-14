"""Intelligent market scanner.

Continuously discovers suitable short-term scalping candidates by volume,
spread, volatility, momentum, relative volume, and activity, using the
configured exchange adapter. Dynamically lists available futures pairs.
"""
import logging
import time
from typing import Any, Dict, List

import pandas as pd

from app.engine import analysis, microstructure
from app.exchanges.adapter import ExchangeAdapter

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(self, adapter: ExchangeAdapter, config: Dict[str, Any]):
        self.adapter = adapter
        self.config = config or {}
        self.results: List[Dict[str, Any]] = []
        self.last_scan: float = 0.0
        self._universe_cache: List[str] = []
        self._universe_ts: float = 0.0

    async def refresh_universe(self) -> List[str]:
        """Discover tradable futures symbols dynamically."""
        now = time.time()
        if self._universe_cache and now - self._universe_ts < 300:
            return self._universe_cache
        try:
            caps = await self.adapter.load_capabilities()
            symbols = [s for s in caps["symbols"] if ":USDT" in s or "/USDT" in s]
            self._universe_cache = symbols
            self._universe_ts = now
        except Exception as exc:
            logger.warning("universe refresh failed: %s", exc)
        return self._universe_cache

    async def prescreen(self, max_symbols: int) -> List[str]:
        """Rank by 24h volume from tickers, take top-N liquid candidates."""
        symbols = await self.refresh_universe()
        if not symbols:
            return []
        try:
            tickers = await self.adapter.client.fetch_tickers(symbols[:200])
        except Exception:
            tickers = {}
        rows = []
        for sym, t in tickers.items():
            quote = float(t.get("quoteVolume") or 0)
            if quote <= 0:
                continue
            spread_pct = 0.0
            bid, ask = t.get("bid"), t.get("ask")
            if bid and ask and bid > 0:
                spread_pct = (ask - bid) / bid * 100
            rows.append((sym, quote, spread_pct))
        rows.sort(key=lambda r: r[1], reverse=True)
        min_vol = float(self.config.get("minVolumeUsd", 5_000_000))
        max_spread = float(self.config.get("maxSpreadPct", 0.08))
        return [s for s, v, sp in rows if v >= min_vol and sp <= max_spread][:max_symbols]

    async def scan(self, max_symbols: int = 40, primary_tf: str = "1m") -> List[Dict[str, Any]]:
        """Full scan: prescreen then evaluate 1m behavior per candidate."""
        candidates = await self.prescreen(max_symbols)
        results: List[Dict[str, Any]] = []
        for sym in candidates:
            try:
                ohlcv = await self.adapter.fetch_ohlcv(sym, timeframe=primary_tf, limit=120)
                if not ohlcv or len(ohlcv) < 30:
                    continue
                df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"]).dropna().reset_index(drop=True)
                price = float(df["close"].iloc[-1])
                vol_usd = float(df["volume"].tail(20).sum() * price)
                a = analysis.atr(df).iloc[-1]
                atr_pct = float(a / price * 100) if price else 0.0
                bid_ask = await self.adapter.fetch_order_book(sym, limit=1)
                bid = bid_ask["bids"][0][0] if bid_ask["bids"] else price * 0.999
                ask = bid_ask["asks"][0][0] if bid_ask["asks"] else price * 1.001
                sp = microstructure.spread_metrics(bid, ask)
                rv = microstructure.relative_volume(df)
                mom = microstructure.momentum_score(df)
                acc = microstructure.price_acceleration(df)
                score = (
                    min(vol_usd / 1e8, 1.0) * 0.25
                    + min(atr_pct / 0.5, 1.0) * 0.25
                    - min(sp["spread_pct"] / 0.05, 1.0) * 0.2
                    + min(rv, 3) / 3 * 0.2
                    + max(0.0, mom) * 0.15
                    + abs(acc) * 0.1
                )
                results.append({
                    "symbol": sym,
                    "price": price,
                    "volumeUsd": vol_usd,
                    "atrPct": round(atr_pct, 4),
                    "spreadPct": round(sp["spread_pct"], 4),
                    "relativeVolume": round(rv, 2),
                    "momentum": round(mom, 3),
                    "acceleration": round(acc, 4),
                    "score": round(float(max(0.0, min(score, 1.0))), 3),
                })
            except Exception as exc:
                logger.debug("scan %s failed: %s", sym, exc)
                continue
        results.sort(key=lambda r: r["score"], reverse=True)
        self.results = results
        self.last_scan = time.time()
        return results

    async def snapshot(self) -> List[Dict[str, Any]]:
        if not self.results or time.time() - self.last_scan > 60:
            await self.scan(
                max_symbols=int(self.config.get("maxSymbols", 40)),
                primary_tf=self.config.get("primaryTimeframe", "1m"),
            )
        return self.results[:20]