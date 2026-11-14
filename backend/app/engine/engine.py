"""Persistent background trading engine.

Runs continuously on Railway independent of frontend connections:
market data ingestion (native exchange WebSockets + REST), scanner, analysis,
probability updates, decision evaluation. Opening real positions happens
ONLY when trading is explicitly activated via persisted state transitions
(START/STOP/HALT).
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
from app.engine.websocket_feeds import ExchangeWebSocketFeed
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
from app.services.trade_recorder import TradeRecorder
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
        self.ws_feeds: Dict[str, ExchangeWebSocketFeed] = {}
        self.recorders: Dict[str, TradeRecorder] = {}
        self.missions: Dict[str, MissionEngine] = {}
        self.opportunities: List[Opportunity] = []
        self.equity: float = 0.0
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_scan = 0.0
        self._vault: Optional[CredentialVault] = None
        self._state_user_id: Optional[str] = None

    async def start(self) -> asyncio.Task:
        self._running = True
        await self._restore_state_on_startup()
        self._task = asyncio.create_task(self._run_loop())
        return self._task

    async def stop(self) -> None:
        self._running = False
        for feed in self.ws_feeds.values():
            await feed.stop()
        self.ws_feeds.clear()
        for adapter in self.adapters.values():
            await adapter.close()
        self.adapters.clear()

    def _ensure_vault(self) -> None:
        if self._vault is None:
            self._vault = CredentialVault(self.settings.credential_encryption_key)

    async def _restore_state_on_startup(self) -> None:
        """Restore persisted settings and trading state after a backend
        restart so a Railway redeploy neither loses the user's risk/scanner
        configuration nor silently re-enables live trading."""
        try:
            resp = self.db.table("app_state").select("*").order("updated_at", desc=True).limit(1).execute()
            rows = resp.data or []
        except Exception as exc:
            logger.warning("state restore failed: %s", exc)
            return
        if not rows:
            return
        row = rows[0]
        try:
            state_value = row.get("state")
            if state_value:
                self.state = TradingState(state_value)
                logger.info("restored trading state: %s", self.state.value)
            self._state_user_id = row.get("user_id")
            if self._state_user_id:
                self.recorders[self._state_user_id] = TradeRecorder(self.db, self._state_user_id)
        except Exception as exc:
            logger.warning("state restore parse failed: %s", exc)
        # restore saved risk + scanner settings (written by PUT /settings endpoints)
        try:
            resp = self.db.table("user_settings").select("*").limit(1).execute()
            rows = resp.data or []
            if rows:
                saved = rows[0]
                risk_saved = saved.get("risk_settings") or {}
                if risk_saved:
                    self.risk.settings_update(RiskSettings(**risk_saved))
                    logger.info("restored risk settings")
                scanner_saved = saved.get("scanner_settings") or {}
                if scanner_saved:
                    self.scanner_config = ScannerConfig(**scanner_saved)
                    logger.info("restored scanner settings")
        except Exception as exc:
            logger.warning("settings restore failed: %s", exc)

    def _ensure_ws_feed(self, exchange_name: str) -> None:
        """Create and start the native WebSocket feed for an exchange once."""
        if exchange_name in self.ws_feeds:
            return
        feed = ExchangeWebSocketFeed(
            exchange=exchange_name,
            on_tick=self._on_ws_tick,
        )
        feed.start()
        self.ws_feeds[exchange_name] = feed
        logger.info("WS feed started: %s", exchange_name)

    def _on_ws_tick(self, exchange_name: str, raw_symbol: str, price: float, size: float) -> None:
        """Map a raw WS symbol back to its ccxt symbol and aggregate into 1m/2m candles."""
        for adapter in self.adapters.values():
            if adapter.exchange_id.value != exchange_name:
                continue
            # find ccxt symbol for this raw symbol
            mapped = self._symbol_map.get((exchange_name, raw_symbol))
            if mapped:
                self.candles.ensure_series(exchange_name, mapped, "1m")
                self.candles.ensure_series(exchange_name, mapped, "2m")
                # update_from_trade is async; schedule without blocking the WS loop
                try:
                    loop = asyncio.get_event_loop()
                    asyncio.ensure_future(
                        self.candles.update_from_trade(exchange_name, mapped, price, size)
                    )
                except RuntimeError:
                    pass
            break

    _symbol_map: Dict[tuple, str] = {}

    def _rebuild_symbol_map(self) -> None:
        """Map raw exchange symbols (from WS) to ccxt symbols using loaded markets."""
        m: Dict[tuple, str] = {}
        for adapter in self.adapters.values():
            ex = adapter.exchange_id.value
            try:
                markets = adapter.client.markets or {}
            except Exception:
                markets = {}
            for sym, market in markets.items():
                m[(ex, market.get("id"))] = sym
        self._symbol_map = m

    async def load_user_exchanges(self, user_id: str) -> List[str]:
        """Load encrypted exchange configs for a user and create adapters."""
        self._ensure_vault()
        if user_id not in self.recorders:
            self.recorders[user_id] = TradeRecorder(self.db, user_id)
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
                # native WS market data for this exchange (public channels, no keys)
                self._ensure_ws_feed(adapter.exchange_id.value)
                logger.info("Exchange connected: %s (%s) user=%s api=%s",
                            row["exchange"], row.get("product"), user_id, mask_secret(api_key))
            except Exception as exc:
                logger.error("adapter init failed for config %s: %s", cfg_id, exc)
        self._rebuild_symbol_map()
        # if trading was active before a restart, honor it now that adapters exist
        if self.state == TradingState.trading_active and connected and self._state_user_id == user_id:
            logger.info("trading was ACTIVE before restart; engine resumed with loaded exchanges")
        return connected

    def _persist_state(self, user_id: str) -> None:
        self._state_user_id = user_id
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

    def _user_id_for_execution(self) -> Optional[str]:
        if self._state_user_id and self._state_user_id in self.recorders:
            return self._state_user_id
        if len(self.recorders) == 1:
            return next(iter(self.recorders))
        return None

    async def refresh_equity(self) -> None:
        """Fetch account equity from the first connected exchange so the
        dashboard balance reflects the real account."""
        for adapter in self.adapters.values():
            try:
                balance = await adapter.fetch_balance()
                equity = balance["equity"]
                if equity > 0:
                    self.equity = equity
                    self.risk.update_equity(equity)
                break
            except Exception as exc:
                logger.warning("equity refresh failed: %s", exc)
                break

    async def _run_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                if now - self._last_scan >= SCAN_INTERVAL:
                    await self._scan_all()
                    self._last_scan = now
                if self.state == TradingState.trading_active and self.adapters:
                    await self._maybe_enter()
                for ex in self.executors.values():
                    await ex.manage()
                    await self._record_closed_trades(ex)
                if self.adapters and (now - self._last_scan) % 30 < MANAGE_INTERVAL:
                    await self.refresh_equity()
                await asyncio.sleep(MANAGE_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("engine loop error: %s", exc)
                await asyncio.sleep(5)

    async def _record_closed_trades(self, ex: ExecutionEngine) -> None:
        user_id = self._user_id_for_execution()
        if user_id is None:
            return
        recorder = self.recorders[user_id]
        for pos in ex.drain_closed():
            recorder.record(
                exchange=pos.exchange,
                symbol=pos.symbol,
                product=pos.product,
                side=pos.side.value,
                qty=pos.qty,
                entry_price=pos.entry_price,
                exit_price=pos.last_price,
                realized_pnl=pos.realized_pnl,
                fees=pos.estimated_fees,
                notes=pos.exit_reason,
            )
            mission = self.missions.get(user_id)
            if mission:
                mission.on_trade_closed(pos.realized_pnl)

    async def _scan_all(self) -> None:
        all_results: List[Opportunity] = []
        ws_symbols: Dict[str, List[str]] = {}
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
                    # collect raw ids for the WS feed of this exchange
                    ws_symbols.setdefault(adapter.exchange_id.value, []).append(r["symbol"])
            except Exception as exc:
                logger.warning("scan failed for %s: %s", cfg_id, exc)
        all_results.sort(key=lambda o: o.score, reverse=True)
        self.opportunities = all_results[:20]
        # keep native WS feeds subscribed to the current scan candidates
        self._rebuild_symbol_map()
        for exchange_name, symbols in ws_symbols.items():
            feed = self.ws_feeds.get(exchange_name)
            if feed is not None:
                feed.set_symbols(symbols[:50])

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
            message=f"equity:{self.equity:.2f}" if self.equity > 0 else "",
        )
