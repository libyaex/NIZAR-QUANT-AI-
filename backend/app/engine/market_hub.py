"""Market hub: 24/7 key-less market data for every configured exchange.

Per exchange it discovers tradable USDT perpetuals, pre-screens them by volume,
spread and activity, pulls candles + order books concurrently, runs the unified
decision engine, keeps live candles fresh through native WebSockets, and
exposes the results to the API and the execution engine. It never needs API
keys and never places orders.
"""
import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from app.engine import analysis
from app.engine.candles import CandleManager, resample_ohlcv
from app.engine.decision import DecisionEngine
from app.engine.probability import ProbabilityEngine
from app.engine.websocket_feeds import ExchangeWebSocketFeed
from app.exchanges.adapter import PublicMarket
from app.models import ExchangeID, Opportunity, ProductType, RiskSettings, ScannerConfig, TradingDecision

logger = logging.getLogger(__name__)

TF_MINUTES = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15}
OHLCV_LIMIT = 150
CONCURRENCY = 6
CONFIRM_TOP = 8


def _hint(msg: str) -> str:
    low = msg.lower()
    if any(k in low for k in ("451", "restricted location", "403", "forbidden", "cloudfront", "not available")):
        return ("This exchange blocks the server's region. In Railway, move the service to a supported "
                "region (EU West is usually safest) or remove it from PUBLIC_EXCHANGES.")
    return ""


@dataclass
class ExchangeState:
    name: str
    market: PublicMarket
    ws: ExchangeWebSocketFeed
    status: str = "starting"          # starting | ok | error
    error: str = ""
    hint: str = ""
    universe: int = 0
    scanned: int = 0
    last_scan: float = 0.0
    scan_ms: int = 0
    fails: int = 0
    rows: List[Opportunity] = field(default_factory=list)
    meta: Dict[str, Dict[str, float]] = field(default_factory=dict)
    id_map: Dict[str, str] = field(default_factory=dict)
    task: Optional[asyncio.Task] = None


class MarketHub:
    def __init__(self, exchanges: List[str], interval: int,
                 get_scanner: Callable[[], ScannerConfig], get_risk: Callable[[], RiskSettings]):
        self.interval = max(10, interval)
        self.get_scanner = get_scanner
        self.get_risk = get_risk
        self.candles = CandleManager()
        self.probability = ProbabilityEngine()
        self.decision = DecisionEngine(self.probability)
        self.states: Dict[str, ExchangeState] = {}
        self._cpu_lock = asyncio.Lock()
        self._trained: Dict[tuple, int] = {}
        self._running = False
        for name in exchanges:
            try:
                eid = ExchangeID(name)
            except ValueError:
                logger.warning("unknown exchange in PUBLIC_EXCHANGES: %s", name)
                continue
            self.states[name] = ExchangeState(
                name=name, market=PublicMarket(eid, ProductType.futures),
                ws=ExchangeWebSocketFeed(name, self._on_tick))

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._running = True
        for st in self.states.values():
            st.ws.start()
            st.task = asyncio.create_task(self._loop(st))

    async def stop(self) -> None:
        self._running = False
        for st in self.states.values():
            await st.ws.stop()
            if st.task:
                st.task.cancel()
            await st.market.close()

    def market_for(self, exchange: str) -> Optional[PublicMarket]:
        st = self.states.get(exchange)
        return st.market if st else None

    # ------------------------------------------------------------------ ticks
    def _on_tick(self, exchange: str, market_id: str, price: float, ts_ms: int) -> None:
        st = self.states.get(exchange)
        sym = st.id_map.get(market_id) if st else None
        if sym:
            self.candles.apply_tick(exchange, sym, price, ts_ms)

    # ------------------------------------------------------------------ loop
    async def _loop(self, st: ExchangeState) -> None:
        while self._running:
            started = time.time()
            try:
                await self._scan(st)
                st.status, st.error, st.hint, st.fails = "ok", "", "", 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                st.fails += 1
                st.status = "error"
                st.error = f"{type(exc).__name__}: {str(exc)[:180]}"
                st.hint = _hint(str(exc))
                logger.warning("scan failed for %s: %s", st.name, st.error)
            st.scan_ms = int((time.time() - started) * 1000)
            delay = self.interval if st.fails == 0 else min(120, self.interval * (2 ** min(st.fails, 3)))
            await asyncio.sleep(max(1.0, delay - (time.time() - started)))

    async def _prescreen(self, st: ExchangeState, cfg: ScannerConfig) -> List[str]:
        universe = await st.market.universe()
        st.universe = len(universe)
        tickers = await st.market.fetch_tickers()
        ranked = []
        st.meta = {}
        for sym in universe:
            t = tickers.get(sym)
            if not t:
                continue
            last = float(t.get("last") or t.get("close") or 0)
            qv = float(t.get("quoteVolume") or 0)
            if qv <= 0 and t.get("baseVolume") and last:
                qv = float(t["baseVolume"]) * last
            if qv <= 0 or last <= 0:
                continue
            bid, ask = t.get("bid"), t.get("ask")
            spread = (float(ask) - float(bid)) / last * 100 if bid and ask else 0.0
            chg = float(t.get("percentage") or 0)
            st.meta[sym] = {"volume24hUsd": qv, "change24hPct": chg, "spreadPct": spread}
            ranked.append((sym, qv, spread, chg))
        eligible = [r for r in ranked if r[1] >= cfg.minVolumeUsd and r[2] <= cfg.maxSpreadPct * 2]
        if not eligible:  # thresholds too strict for this venue: still show the most liquid markets
            eligible = sorted(ranked, key=lambda r: r[1], reverse=True)[: cfg.maxSymbols]
        eligible.sort(key=lambda r: math.log10(r[1]) + min(abs(r[3]), 15) / 5, reverse=True)
        return [r[0] for r in eligible[: cfg.maxSymbols]]

    async def _fetch_symbol(self, st: ExchangeState, sym: str, sem: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                ohlcv, book = await asyncio.gather(
                    st.market.fetch_ohlcv(sym, "1m", OHLCV_LIMIT),
                    st.market.fetch_order_book(sym, 20))
            except Exception as exc:
                logger.debug("fetch %s %s failed: %s", st.name, sym, exc)
                return None
        if not ohlcv or len(ohlcv) < 40:
            return None
        self.candles.seed_from_rest(st.name, sym, "1m", ohlcv)
        return {"sym": sym, "book": book}

    async def _fetch_confirmations(self, st: ExchangeState, sym: str, sem: asyncio.Semaphore) -> None:
        async with sem:
            for tf in ("5m", "15m"):
                try:
                    self.candles.seed_from_rest(st.name, sym, tf, await st.market.fetch_ohlcv(sym, tf, 60))
                except Exception as exc:
                    logger.debug("confirm %s %s %s: %s", st.name, sym, tf, exc)

    def _dfs(self, exchange: str, sym: str) -> Dict[str, pd.DataFrame]:
        d1 = self.candles.get_df(exchange, sym, "1m")
        out = {"1m": d1}
        for tf in ("3m", "5m", "15m"):
            df = self.candles.get_df(exchange, sym, tf)
            if df.empty and not d1.empty:
                df = resample_ohlcv(d1, TF_MINUTES[tf])
            out[tf] = df
        return out

    def _evaluate(self, st: ExchangeState, jobs: List[Dict[str, Any]]) -> List[Opportunity]:
        """CPU-bound; runs in a worker thread, serialised by ``_cpu_lock``."""
        cfg, risk = self.get_scanner(), self.get_risk()
        out: List[Opportunity] = []
        for job in jobs:
            sym, book = job["sym"], job["book"]
            dfs = self._dfs(st.name, sym)
            df1 = dfs["1m"]
            # online learning: the previous COMPLETED candle's outcome is now known
            if len(df1) > 45:
                ts_prev = int(df1["ts"].iloc[-2])
                if self._trained.get((st.name, sym)) != ts_prev:
                    self._trained[(st.name, sym)] = ts_prev
                    self.probability.record_outcome(df1.iloc[:-2], float(df1["close"].iloc[-2]))
            bids, asks = book["bids"], book["asks"]
            opp = self.decision.evaluate(
                st.name, sym, "futures", dfs,
                book={"bid": bids[0][0] if bids else None, "ask": asks[0][0] if asks else None,
                      "bids": bids, "asks": asks},
                taker_fee_pct=risk.takerFeePct, max_spread_pct=cfg.maxSpreadPct,
                min_atr_pct=cfg.minAtrPct, min_score=risk.minOpportunityScore,
                meta=st.meta.get(sym))
            if opp:
                out.append(opp)
        return out

    @staticmethod
    def _sort(rows: List[Opportunity]) -> List[Opportunity]:
        return sorted(rows, key=lambda o: (o.decision != TradingDecision.HOLD, o.score), reverse=True)

    async def _scan(self, st: ExchangeState) -> None:
        cfg = self.get_scanner()
        candidates = await self._prescreen(st, cfg)
        sem = asyncio.Semaphore(CONCURRENCY)
        fetched = [r for r in await asyncio.gather(*(self._fetch_symbol(st, s, sem) for s in candidates)) if r]
        if not fetched:
            raise RuntimeError("no candle data returned (exchange unreachable or rate-limited)")
        async with self._cpu_lock:
            rows = await asyncio.to_thread(self._evaluate, st, fetched)
        # second pass: real 5m/15m candles for the strongest candidates
        top = [o for o in self._sort(rows)[:CONFIRM_TOP]]
        if top:
            await asyncio.gather(*(self._fetch_confirmations(st, o.symbol, sem) for o in top))
            by_sym = {j["sym"]: j for j in fetched}
            async with self._cpu_lock:
                refined = await asyncio.to_thread(self._evaluate, st, [by_sym[o.symbol] for o in top])
            refined_map = {o.symbol: o for o in refined}
            rows = [refined_map.get(o.symbol, o) for o in rows]
        st.rows = self._sort(rows)
        st.scanned = len(fetched)
        st.last_scan = time.time()
        # keep live candles fresh for the best markets via native WebSocket
        st.id_map = {}
        for o in st.rows[:20]:
            m = st.market.market(o.symbol)
            if m and m.get("id"):
                st.id_map[m["id"]] = o.symbol
        st.ws.set_symbols(list(st.id_map))

    # ------------------------------------------------------------------ queries
    def opportunities(self, include_hold: bool = False) -> List[Opportunity]:
        rows = [o for st in self.states.values() for o in st.rows]
        if not include_hold:
            rows = [o for o in rows if o.decision != TradingDecision.HOLD]
        return self._sort(rows)

    def latest(self, exchange: str, symbol: str) -> Optional[Opportunity]:
        st = self.states.get(exchange)
        return next((o for o in (st.rows if st else []) if o.symbol == symbol), None)

    def status(self) -> List[Dict[str, Any]]:
        now = time.time()
        out = []
        for st in self.states.values():
            out.append({
                "id": st.name, "status": st.status, "error": st.error, "hint": st.hint,
                "symbols": st.universe, "scanned": st.scanned,
                "signals": sum(1 for o in st.rows if o.decision != TradingDecision.HOLD),
                "lastScanAgoSec": int(now - st.last_scan) if st.last_scan else None,
                "scanMs": st.scan_ms,
                "ws": {"connected": st.ws.connected, "ticks": st.ws.ticks,
                       "lastTickAgoSec": int(now - st.ws.last_tick) if st.ws.last_tick else None,
                       "error": st.ws.last_error},
            })
        return out

    async def chart(self, exchange: str, symbol: str, tf: str = "1m", limit: int = 200) -> Dict[str, Any]:
        """Candles + indicator overlays + the live decision breakdown."""
        st = self.states.get(exchange)
        if st is None:
            raise KeyError(f"exchange {exchange} is not configured")
        if tf not in TF_MINUTES:
            raise ValueError("timeframe must be one of " + ", ".join(TF_MINUTES))
        series = self.candles.get_series(exchange, symbol, "1m")
        if series is None or time.time() - series.last_update > 90:
            self.candles.seed_from_rest(exchange, symbol, "1m",
                                        await st.market.fetch_ohlcv(symbol, "1m", OHLCV_LIMIT))
        if tf in ("1m", "2m"):
            df = self.candles.get_df(exchange, symbol, "1m")
            df = resample_ohlcv(df, 2) if tf == "2m" else df
        else:
            s2 = self.candles.get_series(exchange, symbol, tf)
            if s2 is None or time.time() - s2.last_update > 90:
                self.candles.seed_from_rest(exchange, symbol, tf, await st.market.fetch_ohlcv(symbol, tf, OHLCV_LIMIT))
            df = self.candles.get_df(exchange, symbol, tf)
        if df.empty:
            raise RuntimeError("no candle data available")
        df = df.tail(limit).reset_index(drop=True)
        c = df["close"]
        e9, e21, bb = analysis.ema(c, 9), analysis.ema(c, 21), analysis.bollinger(c)
        typical = (df["high"] + df["low"] + df["close"]) / 3
        vol = df["volume"].replace(0, float("nan"))
        vwap_line = ((typical * vol).cumsum() / vol.cumsum()).bfill()

        def line(s: pd.Series) -> List[Dict[str, float]]:
            return [{"time": int(t // 1000), "value": float(v)} for t, v in zip(df["ts"], s) if pd.notna(v)]

        book = await st.market.fetch_order_book(symbol, 20)
        dfs = self._dfs(exchange, symbol)
        cfg, risk = self.get_scanner(), self.get_risk()
        async with self._cpu_lock:
            analysis_out = await asyncio.to_thread(
                self.decision.analyze, dfs,
                {"bid": book["bids"][0][0] if book["bids"] else None,
                 "ask": book["asks"][0][0] if book["asks"] else None,
                 "bids": book["bids"], "asks": book["asks"]},
                risk.takerFeePct, cfg.maxSpreadPct, cfg.minAtrPct, risk.minOpportunityScore)
        if analysis_out:
            analysis_out["decision"] = analysis_out["decision"].value
            analysis_out["direction"] = analysis_out["direction"].value
        return {
            "exchange": exchange, "symbol": symbol, "timeframe": tf,
            "candles": [{"time": int(r.ts // 1000), "open": r.open, "high": r.high, "low": r.low,
                         "close": r.close, "volume": r.volume} for r in df.itertuples()],
            "overlays": {"ema9": line(e9), "ema21": line(e21), "vwap": line(vwap_line),
                         "bbUpper": line(bb["upper"]), "bbLower": line(bb["lower"])},
            "analysis": analysis_out,
        }
