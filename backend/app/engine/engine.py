"""Persistent trading engine.

Runs 24/7 on Railway independent of any browser:
  * MarketHub: key-less market data, scanner, analysis for every exchange.
  * Execution: paper (simulated fills on real prices) or live (signed orders).
Real positions are opened ONLY while trading is explicitly active
(START / STOP / HALT are persisted, backend-controlled state transitions).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.engine.execution import ExecutionEngine
from app.engine.market_hub import MarketHub
from app.engine.mission import MissionEngine
from app.engine.risk import RiskManager
from app.exchanges.adapter import ExchangeAdapter, PaperAccount, PaperAdapter
from app.models import (EngineStatusOut, ExchangeID, ProductType, RiskSettings, ScannerConfig,
                        TradingMode, TradingState)
from app.services.trade_recorder import TradeRecorder
from app.services.vault import CredentialVault, mask_secret

logger = logging.getLogger(__name__)

LOOP_INTERVAL = 5
EQUITY_INTERVAL = 20
RECONCILE_INTERVAL = 30
MISSION_INTERVAL = 20
MAX_ENTRIES_PER_CYCLE = 2
MAX_SIGNAL_AGE_SEC = 120


class TradingEngine:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.risk = RiskManager(RiskSettings())
        self.scanner_config = ScannerConfig()
        self.hub = MarketHub(settings.market_exchanges, settings.scan_interval_seconds,
                             get_scanner=lambda: self.scanner_config, get_risk=lambda: self.risk.settings)
        self.state = TradingState.engine_ready
        self.started_at = time.time()
        self.owner_id: Optional[str] = None
        self.paper = PaperAccount(self.risk.settings.paperBalance)
        self.paper_executors: Dict[str, ExecutionEngine] = {}
        self.live_adapters: Dict[str, ExchangeAdapter] = {}
        self.live_executors: Dict[str, ExecutionEngine] = {}
        self.live_status: Dict[str, Dict] = {}
        self.recorders: Dict[str, TradeRecorder] = {}
        self.missions: Dict[str, MissionEngine] = {}
        self.equity = 0.0
        self.equity_by_key: Dict[str, float] = {}
        self._vault: Optional[CredentialVault] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._baseline_pending = True

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> asyncio.Task:
        self._running = True
        await self._restore()
        await self.hub.start()
        if self.owner_id:
            await self.load_user_exchanges(self.owner_id)
        self._task = asyncio.create_task(self._run_loop())
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        await self.hub.stop()
        for a in self.live_adapters.values():
            await a.close()

    def vault(self) -> CredentialVault:
        if self._vault is None:
            self._vault = CredentialVault(self.settings.credential_encryption_key)
        return self._vault

    async def _restore(self) -> None:
        """Restore persisted trading state and settings after a restart."""
        try:
            rows = self.db.table("app_state").select("*").order("updated_at", desc=True).limit(1).execute().data or []
        except Exception as exc:
            logger.warning("state restore failed: %s", exc)
            return
        if not rows:
            return
        row = rows[0]
        self.owner_id = row.get("user_id")
        try:
            self.state = TradingState(row.get("state") or "engine_ready")
        except ValueError:
            self.state = TradingState.trading_stopped
        if self.state == TradingState.emergency_halt:
            self.risk.emergency_halt("user_halt")
        logger.info("restored trading state=%s owner=%s", self.state.value, self.owner_id)
        try:
            q = self.db.table("user_settings").select("*").eq("user_id", self.owner_id).limit(1).execute()
            saved = (q.data or [{}])[0]
            if saved.get("risk_settings"):
                self.risk.settings_update(RiskSettings(**saved["risk_settings"]))
                self.paper.reset(self.risk.settings.paperBalance)
            if saved.get("scanner_settings"):
                self.scanner_config = ScannerConfig(**saved["scanner_settings"])
        except Exception as exc:
            logger.warning("settings restore failed: %s", exc)

    # ------------------------------------------------------------------ executors
    @property
    def mode(self) -> TradingMode:
        return self.risk.settings.tradingMode

    def _ensure_paper_executors(self) -> None:
        for name, st in self.hub.states.items():
            if name not in self.paper_executors:
                adapter = PaperAdapter(st.market, self.paper, self.risk.settings.takerFeePct)
                self.paper_executors[name] = ExecutionEngine(adapter, self.risk, self.hub.latest)

    def executors(self) -> List[ExecutionEngine]:
        """Executors that may OPEN trades in the current mode."""
        if self.mode == TradingMode.live:
            return list(self.live_executors.values())
        self._ensure_paper_executors()
        return list(self.paper_executors.values())

    def all_executors(self) -> List[ExecutionEngine]:
        """Every executor holding positions (managed regardless of mode)."""
        return list(self.paper_executors.values()) + list(self.live_executors.values())

    def open_total(self) -> int:
        return sum(e.open_position_count() for e in self.all_executors())

    def total_unrealized(self) -> float:
        return sum(p.unrealizedPnl for e in self.all_executors() for p in e.snapshots())

    def snapshots(self):
        return [p for e in self.all_executors() for p in e.snapshots()]

    # ------------------------------------------------------------------ live exchanges
    async def load_user_exchanges(self, user_id: str) -> List[str]:
        """(Re)build signed adapters from the user's encrypted configs."""
        self.recorders.setdefault(user_id, TradeRecorder(self.db, user_id))
        self.missions.setdefault(user_id, MissionEngine(self.db, user_id))
        try:
            rows = self.db.table("exchange_configs").select("*").eq("user_id", user_id).execute().data or []
        except Exception as exc:
            logger.warning("load exchanges failed: %s", exc)
            return []
        connected: List[str] = []
        for row in rows:
            cfg_id = row["id"]
            if cfg_id in self.live_adapters:
                connected.append(cfg_id)
                continue
            await self._connect_config(row)
            if self.live_status.get(cfg_id, {}).get("connected"):
                connected.append(cfg_id)
        return connected

    async def _connect_config(self, row: Dict) -> None:
        cfg_id = row["id"]
        status = {"connected": False, "error": "", "equity": 0.0}
        self.live_status[cfg_id] = status
        try:
            v = self.vault()
            api_key = v.decrypt(row.get("api_key_enc", ""))
            adapter = ExchangeAdapter(
                exchange=ExchangeID(row["exchange"]), product=ProductType(row.get("product", "futures")),
                apiKey=api_key, secret=v.decrypt(row.get("secret_enc", "")),
                password=v.decrypt(row["password_enc"]) if row.get("password_enc") else None,
                testnet=bool(row.get("testnet", False)))
            await adapter.client.load_markets()
            bal = await adapter.fetch_balance()     # proves the credentials work
            status.update(connected=True, equity=bal["equity"])
            self.live_adapters[cfg_id] = adapter
            self.live_executors[cfg_id] = ExecutionEngine(adapter, self.risk, self.hub.latest)
            logger.info("live exchange connected: %s key=%s equity=%.2f", row["exchange"], mask_secret(api_key), bal["equity"])
        except Exception as exc:
            status["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.error("exchange %s connect failed: %s", row.get("exchange"), status["error"])

    async def remove_exchange(self, cfg_id: str) -> None:
        ex = self.live_executors.pop(cfg_id, None)
        if ex and ex.open_position_count():
            self.live_executors[cfg_id] = ex
            raise ValueError("Close this exchange's open positions before disconnecting it")
        adapter = self.live_adapters.pop(cfg_id, None)
        if adapter:
            await adapter.close()
        self.live_status.pop(cfg_id, None)

    # ------------------------------------------------------------------ state machine
    def _persist(self, user_id: str) -> None:
        self.owner_id = user_id
        try:
            self.db.table("app_state").upsert({
                "user_id": user_id, "trading_active": self.state == TradingState.trading_active,
                "state": self.state.value, "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
        except Exception as exc:
            logger.warning("persist state failed: %s", exc)

    async def set_trading(self, user_id: str, action: str) -> TradingState:
        if action == "start":
            if self.mode == TradingMode.live:
                await self.load_user_exchanges(user_id)
                if not self.live_executors:
                    raise ValueError("Live mode needs a connected exchange. Connect API keys or switch to Paper mode.")
            self.risk.resume()
            if self.risk.state.halted:
                raise ValueError(f"Risk protection is active ({self.risk.state.halt_reason}). "
                                 "New trades stay blocked until it clears or you reset risk.")
            self.state = TradingState.trading_active
            logger.info("TRADING ACTIVATED mode=%s user=%s", self.mode.value, user_id)
        elif action == "stop":
            self.state = TradingState.trading_stopped
            logger.info("TRADING STOPPED user=%s (existing positions keep being managed)", user_id)
        elif action == "halt":
            self.state = TradingState.emergency_halt
            self.risk.emergency_halt("user_halt")
        self._persist(user_id)
        return self.state

    def reset_risk(self, user_id: str) -> None:
        self.risk.reset()
        if self.state == TradingState.emergency_halt:
            self.state = TradingState.trading_stopped
            self._persist(user_id)

    async def close_all_positions(self) -> int:
        return sum([await ex.close_all() for ex in self.all_executors()])

    def apply_settings(self, user_id: str, risk: Optional[RiskSettings] = None,
                       scanner: Optional[ScannerConfig] = None) -> None:
        if risk is not None:
            old = self.risk.settings
            if risk.tradingMode != old.tradingMode:
                if self.open_total():
                    raise ValueError("Close all open positions before switching between Paper and Live mode")
                if risk.tradingMode == TradingMode.live and not self.live_executors:
                    raise ValueError("Connect an exchange (Exchange Management) before enabling Live mode")
                if self.state == TradingState.trading_active:
                    self.state = TradingState.trading_stopped      # never switch money mode silently
                    self._persist(user_id)
                self._baseline_pending = True
            if risk.paperBalance != old.paperBalance and not self.paper.positions:
                self.paper.reset(risk.paperBalance)
                self._baseline_pending = True
            self.risk.settings_update(risk)
            for ex in self.paper_executors.values():
                ex.adapter.fee_pct = risk.takerFeePct
        if scanner is not None:
            self.scanner_config = scanner
        row = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        if risk is not None:
            row["risk_settings"] = risk.model_dump(mode="json")
        if scanner is not None:
            row["scanner_settings"] = scanner.model_dump(mode="json")
        try:
            self.db.table("user_settings").upsert(row, on_conflict="user_id").execute()
        except Exception as exc:
            logger.warning("settings persist failed: %s", exc)

    # ------------------------------------------------------------------ equity
    async def refresh_equity(self) -> None:
        if self.mode == TradingMode.paper:
            self.equity = self.paper.equity()
            self.equity_by_key = {"paper": self.equity}
        else:
            total = 0.0
            for cfg_id, adapter in self.live_adapters.items():
                try:
                    eq = (await adapter.fetch_balance())["equity"]
                    self.equity_by_key[cfg_id] = eq
                    self.live_status.setdefault(cfg_id, {})["equity"] = eq
                    total += eq
                except Exception as exc:
                    self.live_status.setdefault(cfg_id, {})["error"] = str(exc)[:200]
            self.equity = total
        if self.equity > 0:
            if self._baseline_pending:
                self.risk.reset_baseline(self.equity)
                self._baseline_pending = False
            else:
                self.risk.update_equity(self.equity)

    # ------------------------------------------------------------------ main loop
    async def _run_loop(self) -> None:
        nxt = {"equity": 0.0, "reconcile": 0.0, "mission": 0.0}
        while self._running:
            try:
                now = time.time()
                if now >= nxt["equity"]:
                    nxt["equity"] = now + EQUITY_INTERVAL
                    await self.refresh_equity()
                if now >= nxt["mission"]:
                    nxt["mission"] = now + MISSION_INTERVAL
                    for m in self.missions.values():
                        m.refresh()
                if self.state == TradingState.trading_active:
                    await self._maybe_enter()
                for ex in self.all_executors():
                    await ex.manage()
                    self._record_closed(ex)
                if now >= nxt["reconcile"]:
                    nxt["reconcile"] = now + RECONCILE_INTERVAL
                    for ex in self.live_executors.values():
                        await ex.reconcile(adopt=True)
                        self._record_closed(ex)
                await asyncio.sleep(LOOP_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("engine loop error")
                await asyncio.sleep(5)

    def _record_closed(self, ex: ExecutionEngine) -> None:
        for pos in ex.drain_closed():
            uid = self.owner_id
            if uid is None or uid not in self.recorders:
                continue
            self.recorders[uid].record(
                exchange=pos.exchange, symbol=pos.symbol, product=pos.product, side=pos.side.value,
                qty=pos.qty, entry_price=pos.entry_price, exit_price=pos.last_price,
                realized_pnl=pos.realized_pnl, fees=pos.fees, notes=f"{pos.mode}|{pos.exit_reason}")
            mission = self.missions.get(uid)
            if mission:
                mission.on_trade_closed(pos.realized_pnl)

    async def _maybe_enter(self) -> None:
        if self.risk.state.halted:
            return
        mission = self.missions.get(self.owner_id or "")
        if mission:
            allowed, _ = mission.gate()
            if not allowed:
                return
        execs = {ex.exchange_name: ex for ex in self.executors()}
        if not execs:
            return
        now = datetime.now(timezone.utc)
        entries = 0
        for opp in self.hub.opportunities():
            ex = execs.get(opp.exchange)
            if ex is None or (now - opp.ts).total_seconds() > MAX_SIGNAL_AGE_SEC:
                continue
            if self.open_total() >= self.risk.settings.maxConcurrentPositions:
                return
            key = "paper" if self.mode == TradingMode.paper else next(
                (k for k, v in self.live_executors.items() if v is ex), "")
            equity = self.equity_by_key.get(key) or self.equity
            if equity <= 0:
                continue
            if await ex.try_enter(opp, equity, self.open_total()):
                entries += 1
                if entries >= MAX_ENTRIES_PER_CYCLE:
                    return

    # ------------------------------------------------------------------ status
    def status(self) -> EngineStatusOut:
        hub_ok = [s["id"] for s in self.hub.status() if s["status"] == "ok"]
        state = self.state
        if not hub_ok and self.hub.states:
            state = TradingState.connection_lost
        elif self.state == TradingState.trading_active and self.risk.state.halted:
            state = TradingState.emergency_halt
        msg = ""
        if self.mode == TradingMode.live and not self.live_executors:
            msg = "Live mode selected but no exchange is connected"
        return EngineStatusOut(
            state=state, uptimeSeconds=int(time.time() - self.started_at),
            exchangesConnected=hub_ok, scannedSymbols=sum(s["scanned"] for s in self.hub.status()),
            openPositions=self.open_total(), tradingActive=self.state == TradingState.trading_active,
            mode=self.mode.value, equity=round(self.equity, 4),
            haltReason=self.risk.state.halt_reason if self.risk.state.halted else "", message=msg)
