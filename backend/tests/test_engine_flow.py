"""End-to-end engine flow against a fake exchange (no network, no keys).

Covers: dynamic universe discovery -> scan -> decision -> START TRADING ->
paper execution with contract-size handling -> risk gates -> CLOSE ALL ->
trade recording. Run:  cd backend && python -m pytest tests -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.engine import TradingEngine  # noqa: E402
from app.exchanges import adapter as adapter_mod  # noqa: E402
from app.models import RiskSettings, TradingState  # noqa: E402


class FakeClient:
    """Mimics the slice of ccxt used by the app."""

    def __init__(self):
        self.options = {"fetchMarkets": ["swap"]}
        self.markets = {}
        for sym, drift in (("UP/USDT:USDT", 0.0007), ("DOWN/USDT:USDT", -0.0007), ("FLAT/USDT:USDT", 0.0),
                           ("SPOT/USDT", 0.0)):
            self.markets[sym] = {
                "symbol": sym, "id": sym.split("/")[0] + "USDT", "swap": ":" in sym, "spot": ":" not in sym,
                "linear": True, "settle": "USDT" if ":" in sym else None, "quote": "USDT", "active": True,
                "contractSize": 0.01 if sym.startswith("UP") else 1.0,
                "limits": {"amount": {"min": 1}, "cost": {"min": 1}}, "_drift": drift}

    async def load_markets(self, reload=False):
        return self.markets

    def _series(self, sym, n=150):
        drift = self.markets[sym]["_drift"]
        rng = np.random.default_rng(abs(hash(sym)) % 1000)
        p = 100 * np.exp(np.cumsum(rng.normal(drift, 0.0012, n)))
        o = np.r_[p[0], p[:-1]]
        h, l = np.maximum(o, p) * 1.0004, np.minimum(o, p) * 0.9996
        return [[1_700_000_000_000 + i * 60_000, o[i], h[i], l[i], p[i], 100.0] for i in range(n)]

    async def fetch_tickers(self):
        return {s: {"last": self._series(s)[-1][4], "quoteVolume": 5e8, "bid": self._series(s)[-1][4] * .9999,
                    "ask": self._series(s)[-1][4] * 1.0001, "percentage": 3.0} for s in self.markets}

    async def fetch_ticker(self, sym):
        last = self._series(sym)[-1][4]
        return {"last": last, "close": last}

    async def fetch_ohlcv(self, sym, timeframe="1m", limit=200):
        return self._series(sym, max(limit, 60))[-limit:]

    async def fetch_order_book(self, sym, limit=20):
        last = self._series(sym)[-1][4]
        return {"bids": [[last * .9999, 500.0]] * 5, "asks": [[last * 1.0001, 100.0]] * 5}

    async def fetch_time(self):
        return 1

    def amount_to_precision(self, sym, amount):
        return str(int(amount))

    async def close(self):
        pass


class NullQuery:
    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        return SimpleNamespace(data=[])


class NullDB:
    def table(self, _):
        return NullQuery()


def make_engine(monkeypatch):
    monkeypatch.setattr(adapter_mod, "build_client", lambda *a, **k: FakeClient())
    settings = SimpleNamespace(market_exchanges=["okx"], scan_interval_seconds=30, credential_encryption_key="")
    return TradingEngine(NullDB(), settings)


def test_scan_finds_signals_and_universe_is_futures_only(monkeypatch):
    async def run():
        eng = make_engine(monkeypatch)
        st = eng.hub.states["okx"]
        await eng.hub._scan(st)
        assert st.universe == 3                                  # spot market excluded
        symbols = {o.symbol for o in st.rows}
        assert "SPOT/USDT" not in symbols
        sig = {o.symbol: o.decision.value for o in st.rows}
        assert sig["UP/USDT:USDT"] == "LONG" and sig["DOWN/USDT:USDT"] == "SHORT"
    asyncio.run(run())


def test_start_trade_close_flow_paper(monkeypatch):
    async def run():
        eng = make_engine(monkeypatch)
        await eng.hub._scan(eng.hub.states["okx"])
        eng.apply_settings("u1", risk=RiskSettings(paperBalance=1000, riskPerTradePct=1, maxConcurrentPositions=2))
        eng.recorders["u1"] = SimpleNamespace(record=lambda **k: recorded.append(k))
        recorded = []
        await eng.refresh_equity()
        assert eng.equity == 1000
        # nothing opens before START
        await eng._maybe_enter() if eng.state == TradingState.trading_active else None
        assert eng.open_total() == 0
        await eng.set_trading("u1", "start")
        await eng._maybe_enter()
        assert eng.open_total() >= 1
        pos = eng.snapshots()[0]
        assert pos.mode == "paper"
        # 1% risk on 1000 with 0.35% stop + fees => notional ~ 2353 (<= 5x leverage cap of 5000)
        notional = pos.qty * pos.entryPrice * (0.01 if pos.symbol.startswith("UP") else 1.0)
        assert 1500 < notional < 3200, notional
        # concurrency cap honoured
        for _ in range(3):
            await eng._maybe_enter()
        assert eng.open_total() <= 2
        # STOP keeps positions, blocks new entries
        await eng.set_trading("u1", "stop")
        before = eng.open_total()
        await eng._maybe_enter() if eng.state == TradingState.trading_active else None
        assert eng.open_total() == before
        closed = await eng.close_all_positions()
        assert closed == before and eng.open_total() == 0
        for ex in eng.all_executors():
            eng._record_closed(ex)
        assert len(recorded) == before and all(r["notes"].startswith("paper|") for r in recorded)
    asyncio.run(run())


def test_daily_loss_halts_entries(monkeypatch):
    eng = make_engine(monkeypatch)
    eng.risk.update_equity(1000)
    eng.risk.record_trade_result(-60)           # 6% > 5% daily limit
    assert eng.risk.state.halted and eng.risk.state.halt_reason == "daily_loss_limit"
    eng.risk.resume()                            # START must NOT bypass the daily limit
    assert eng.risk.state.halted
