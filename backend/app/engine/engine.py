"""Persistent background trading engine.

Runs continuously on Railway independent of frontend connections:
market data ingestion, scanner, analysis, probability updates, decision
evaluation. Opening real positions happens ONLY when trading is explicitly
activated via persisted state transitions (START/STOP/HALT).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.engine.candles import CandleManager
from app.engine.decision import DecisionEngine
from app.engine.execution import ExecutionEngine
from app.engine.mission import MissionEngine
from app.engine.probability import ProbabilityEngine
from app.engine.risk import RiskManager
from app.engine.scanner import MarketScanner
from app.exchanges.adapter import ExchangeAdapter
from app.models import (
    EngineStatusOut,
    ExchangeID,
    Opportunity,
    ProductType,
    RiskSettings,
    ScannerConfig,
    TradingState,
)
from app.services.vault import CredentialVault, mask_secret

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 60
MANAGE_INTERVAL = 5


class TradingEngine:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.candles = CandleManager()
        self.probability = ProbabilityEngine()
        self.decision = DecisionEngine(self.probability)
        self.risk = RiskManager(RiskSettings())
        self.scanner_config = ScannerConfig()
        self.state = TradingState.trading_stopped
        self.started_at = time.time()
        self.adapters: Dict[str, ExchangeAdapter] = {}
        self.scanners: Dict[str, MarketScanner] = {}
        self.executors: Dict[str, ExecutionEngine] = {}
        self.missions: Dict[str, MissionEngine] = {}
        self.opportunities: List[Opportunity] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_scan = 0.0
        self._vault: Optional[CredentialVault] = None

    async def start(self) -> asyncio.Task:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        return self._task

    async def stop(self) -> None:
        self._running = False
        for adapter in self.adapters.values():
            await adapter.close()
        self.adapters.clear()

    def _ensure_vault(self) -> None:
        if self._vault is None:
            self._vault = CredentialVault(self.settings.credential_encryption_key)

    async def load_user_exchanges(self, user_id: str) -> List[str]:
        """Load encrypted exchange configs for a user and create adapters."""
        self._ensure_vault()
        try:
            resp = self.db.table("exchange_configs").select("*").eq("user_id", user_id).execute()
            rows = resp.data or []
        except Exception as exc:
            logger.warning("load exchanges failed: %s", exc)
            rows = []
        connected: List[str] = []
        for row in rows:
            cfg_id = row["id"]
            try:
                api_key = self._vault.decrypt(row.get("api_key_enc", ""))
                secret = self._vault.decrypt(row.get("secret_enc", ""))
                password = self._vault.decrypt(row.get("password_enc", "")) if row.get("password_enc") else None
                adapter = ExchangeAdapter(
                    exchange=ExchangeID(row["exchange"]),
                    product=ProductType(row.get("product", "futures")),
                    apiKey=api_key,
                    secret=secret,
                    password=password,
                    testnet=bool(row.get("testnet", False)),
                )
                ok = await adapter.ping()
                if not ok:
                    logger.warning("exchange %s ping failed for user %s", row["exchange"], user_id)
                self.adapters[cfg_id] = adapter
                self.scanners[cfg_id] = MarketScanner(adapter, self.scanner_config.model_dump())
                self.executors[cfg_id] = ExecutionEngine(
                    adapter=adapter,
                    risk=self.risk,
                    fee_pct=0.05,
                    max_holding_minutes=self.risk.settings.maxHoldingMinutes,
                    trailing_stop_pct=self.risk.settings.trailingStopPct,
                    partial_tp_pct=self.risk.settings.partialTakeProfitPct,
                )
                if user_id not in self.missions:
                    self.missions[user_id] = MissionEngine(self.db, user_id, self.risk)
                connected.append(cfg_id)
                logger.info("Exchange connected: %s (%s) user=%s api=%s",
                            row["exchange"], row.get("product"), user_id, mask_secret(api_key))
            except Exception as exc:
                logger.error("adapter init failed for config %s: %s", cfg_id, exc)
        return connected

    def _persist_state(self, user_id: str) -> None:
        try:
            self.db.table("app_state").upsert({
                "user_id": user_id,
                "trading_active": self.state == TradingState.trading_active,
                "state": self.state.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as exc:
            logger.warning("persist state failed: %s", exc)

    async def set_trading(self, user_id: str, action: str) -> TradingState:
        if action == "start":
            if self.state != TradingState.trading_active:
                self.risk.resume()
                self.state = TradingState.trading_active
                logger.info("TRADING ACTIVATED user=%s", user_id)
        elif action == "stop":
            if self.state == TradingState.trading_active:
                self.state = TradingState.trading_stopped
                logger.info("TRADING STOPPED user=%s — managing existing positions", user_id)
        elif action == "halt":
            self.state = TradingState.emergency_halt
            self.risk.emergency_halt("user_halt")
            logger.warning("EMERGENCY HALT user=%s", user_id)
        self._persist_state(user_id)
        return self.state

    async def close_all_positions(self) -> int:
        total = 0
        for ex in self.executors.values():
            total += await ex.close_all()
        return total

    async def _run_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                if now - self._last_scan >= SCAN_INTERVAL:
                    await self._scan_all()
                    self._last_scan = now
                if self.state == TradingState.trading_active:
                    await self._maybe_enter()
                for ex in self.executors.values():
                    await ex.manage()
                await asyncio.sleep(MANAGE_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("engine loop error: %s", exc)
                await asyncio.sleep(5)

    async def _scan_all(self) -> None:
        all_results: List[Opportunity] = []
        for cfg_id, scanner in self.scanners.items():
            try:
                results = await scanner.scan(
                    max_symbols=self.scanner_config.maxSymbols,
                    primary_tf=self.scanner_config.primaryTimeframe,
                )
                adapter = self.adapters[cfg_id]
                for r in results[:10]:
                    for tf in ("1m", "3m", "5m", "15m"):
                        ohlcv = await adapter.fetch_ohlcv(r["symbol"], timeframe=tf, limit=200)
                        self.candles.seed_from_rest(adapter.exchange_id.value, r["symbol"], tf, ohlcv)
                    dfs = {
                        tf: self.candles.get_df(adapter.exchange_id.value, r["symbol"], tf)
                        for tf in ("1m", "3m", "5m", "15m")
                    }
                    book = await adapter.fetch_order_book(r["symbol"], limit=20)
                    opp = self.decision.evaluate(
                        exchange=adapter.exchange_id.value,
                        symbol=r["symbol"],
                        product="futures",
                        dfs=dfs,
                        book={
                            "bid": book["bids"][0][0] if book["bids"] else None,
                            "ask": book["asks"][0][0] if book["asks"] else None,
                            "bids": book["bids"],
                            "asks": book["asks"],
                        },
                        min_score_override=self.risk.settings.minOpportunityScore,
                    )
                    if opp:
                        all_results.append(opp)
            except Exception as exc:
                logger.warning("scan failed for %s: %s", cfg_id, exc)
        all_results.sort(key=lambda o: o.score, reverse=True)
        self.opportunities = all_results[:20]

    async def _maybe_enter(self) -> None:
        if not self.opportunities:
            return
        for mission in self.missions.values():
            await mission.load_active()
            if not mission.allows_new_trades():
                return
        for opp in self.opportunities:
            for cfg_id, adapter in self.adapters.items():
                if adapter.exchange_id.value != opp.exchange:
                    continue
                ex = self.executors.get(cfg_id)
                if ex is None:
                    continue
                try:
                    balance = await adapter.fetch_balance()
                    equity = balance["equity"]
                    self.risk.update_equity(equity)
                    await ex.try_enter(opp, equity)
                    break
                except Exception as exc:
                    logger.warning("entry attempt failed %s: %s", opp.symbol, exc)
                    continue

    def status(self) -> EngineStatusOut:
        connected = [a.exchange_id.value for a in self.adapters.values()]
        open_positions = sum(ex.open_position_count() for ex in self.executors.values())
        eff_state = TradingState.engine_ready if not connected else self.state
        return EngineStatusOut(
            state=eff_state,
            uptimeSeconds=int(time.time() - self.started_at),
            exchangesConnected=connected,
            scannedSymbols=len(self.opportunities),
            openPositions=open_positions,
            tradingActive=self.state == TradingState.trading_active,
            message="",
        )