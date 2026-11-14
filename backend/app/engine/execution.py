"""Automated execution engine.

Places real orders via exchange adapters when live trading is active:
market/limit entries, stop-loss, take-profit, trailing stop, partial profit,
break-even management, early exit, and reconciliation with actual exchange
positions. Orders are never assumed filled until the exchange confirms them.
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.engine.risk import RiskManager
from app.exchanges.adapter import ExchangeAdapter
from app.models import Opportunity, OrderSide, PositionSnapshot, ProductType, TradingDecision

logger = logging.getLogger(__name__)


@dataclass
class ManagedPosition:
    position_id: str
    exchange: str
    symbol: str
    product: str
    side: OrderSide
    qty: float
    entry_price: float
    leverage: int
    stop_loss: float
    take_profit: float
    fee_pct: float
    opened_at: float
    updated_at: float
    trailing_active: bool = False
    partial_filled: bool = False
    realized_pnl: float = 0.0
    exchange_order_id: Optional[str] = None
    remaining_qty: float = 0.0
    closed: bool = False


class ExecutionEngine:
    def __init__(self, adapter: ExchangeAdapter, risk: RiskManager,
                 fee_pct: float = 0.05, max_holding_minutes: int = 30,
                 trailing_stop_pct: float = 0.25, partial_tp_pct: float = 50.0):
        self.adapter = adapter
        self.risk = risk
        self.fee_pct = fee_pct
        self.max_holding_minutes = max_holding_minutes
        self.trailing_stop_pct = trailing_stop_pct
        self.partial_tp_pct = partial_tp_pct
        self.positions: Dict[str, ManagedPosition] = {}
        self._pending_orders: set = set()  # duplicate prevention by (symbol, side)

    # ------------------------------------------------------------------
    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if not p.closed)

    # ------------------------------------------------------------------
    async def try_enter(self, opp: Opportunity, equity: float) -> Optional[ManagedPosition]:
        if self._is_pending(opp.symbol):
            return None
        ok, reason = self.risk.can_open(self.open_position_count())
        if not ok:
            logger.info("Entry blocked by risk: %s", reason)
            return None

        side = OrderSide.long if opp.decision == TradingDecision.LONG else OrderSide.short
        sl_pct = self.risk.settings.stopLossPct
        market = None
        try:
            markets = await self.adapter.client.load_markets()
            market = markets.get(opp.symbol)
        except Exception:
            market = None
        min_amount = None
        amount_precision = None
        if market:
            limits = market.get("limits", {}).get("amount", {})
            min_amount = limits.get("min")
            amount_precision = market.get("precision", {}).get("amount")

        qty = self.risk.position_size(
            equity=equity,
            price=self._last_price_cache.get(opp.symbol, 0.0) or await self._fetch_price(opp.symbol),
            stop_loss_pct=sl_pct,
            leverage_cap=self.risk.settings.maxLeverage,
            contract_min_amount=min_amount,
            amount_precision=amount_precision,
            taker_fee_pct=self.fee_pct,
        )
        if qty is None:
            logger.info("Position sizing rejected %s", opp.symbol)
            return None

        price = await self._fetch_price(opp.symbol)
        leverage = min(self.risk.settings.maxLeverage, 5)
        await self.adapter.set_leverage(opp.symbol, leverage)
        order_side = "buy" if side == OrderSide.long else "sell"
        self._add_pending(opp.symbol)
        try:
            order = await self.adapter.create_market_order(opp.symbol, order_side, qty)
        except Exception as exc:
            logger.error("Entry order failed %s %s: %s", self.exchange_name(), opp.symbol, exc)
            self._remove_pending(opp.symbol)
            return None
        finally:
            self._remove_pending(opp.symbol)

        filled = self._confirmed_fill(order)
        if not filled:
            logger.warning("Entry not confirmed for %s", opp.symbol)
            return None

        entry_price = float(order.get("average") or order.get("price") or price)
        st = self.risk.stop_and_target_prices(side.value, entry_price)
        pos = ManagedPosition(
            position_id=str(uuid.uuid4()),
            exchange=self.exchange_name(),
            symbol=opp.symbol,
            product=opp.product,
            side=side,
            qty=filled,
            entry_price=entry_price,
            leverage=leverage,
            stop_loss=st["stop_loss"],
            take_profit=st["take_profit"],
            fee_pct=self.fee_pct,
            opened_at=time.time(),
            updated_at=time.time(),
            exchange_order_id=str(order.get("id", "")),
            remaining_qty=filled,
        )
        self.positions[pos.position_id] = pos
        logger.info("OPEN %s %s qty=%s entry=%s", side.value.upper(), pos.symbol, filled, entry_price)
        return pos

    # ------------------------------------------------------------------
    async def manage(self) -> None:
        """Monitor open positions: SL/TP, trailing, partial, break-even, timeout."""
        if not self.positions:
            return
        to_remove: List[str] = []
        for pos in list(self.positions.values()):
            if pos.closed:
                continue
            try:
                price = await self._fetch_price(pos.symbol)
            except Exception:
                continue
            pos.updated_at = time.time()
            pnl_pct = self._pnl_pct(pos, price)
            s = self.risk.settings

            # --- time-based exit ------------------------------------------------
            held_min = (time.time() - pos.opened_at) / 60
            if held_min >= self.max_holding_minutes:
                await self._close(pos, price, "max_holding_time")
                to_remove.append(pos.position_id)
                continue

            # --- stop loss / take profit ---------------------------------------
            if pos.side == OrderSide.long:
                if price <= pos.stop_loss:
                    await self._close(pos, price, "stop_loss")
                    to_remove.append(pos.position_id)
                    continue
                if price >= pos.take_profit:
                    await self._close(pos, price, "take_profit")
                    to_remove.append(pos.position_id)
                    continue
            else:
                if price >= pos.stop_loss:
                    await self._close(pos, price, "stop_loss")
                    to_remove.append(pos.position_id)
                    continue
                if price <= pos.take_profit:
                    await self._close(pos, price, "take_profit")
                    to_remove.append(pos.position_id)
                    continue

            # --- partial take profit --------------------------------------------
            if not pos.partial_filled and pnl_pct >= self.partial_tp_pct / 100 * s.takeProfitPct:
                part = pos.qty * self.partial_tp_pct / 100
                await self._partial_close(pos, price, part)
                # move stop to break-even after partial
                pos.stop_loss = pos.entry_price
                pos.trailing_active = True

            # --- trailing stop ---------------------------------------------------
            if pos.trailing_active:
                trail = self.trailing_stop_pct / 100
                if pos.side == OrderSide.long:
                    new_sl = price * (1 - trail)
                    if new_sl > pos.stop_loss:
                        pos.stop_loss = new_sl
                else:
                    new_sl = price * (1 + trail)
                    if new_sl < pos.stop_loss:
                        pos.stop_loss = new_sl

        for pid in to_remove:
            self.positions.pop(pid, None)

    # ------------------------------------------------------------------
    async def close_all(self, reason: str = "manual_close_all") -> int:
        closed = 0
        for pos in list(self.positions.values()):
            if pos.closed:
                continue
            try:
                price = await self._fetch_price(pos.symbol)
                await self._close(pos, price, reason)
                closed += 1
            except Exception as exc:
                logger.error("close_all %s failed: %s", pos.symbol, exc)
            self.positions.pop(pos.position_id, None)
        return closed

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    async def _close(self, pos: ManagedPosition, price: float, reason: str) -> None:
        qty = pos.remaining_qty or pos.qty
        result = await self.adapter.close_position(pos.symbol, pos.side.value, qty)
        if result is None:
            logger.error("Failed to close %s — will retry next cycle", pos.symbol)
            return
        pnl = self._realized_pnl(pos, price, qty)
        pos.realized_pnl = pnl
        pos.closed = True
        self.risk.record_trade_result(pnl)
        logger.info("CLOSE %s %s pnl=%.4f reason=%s", pos.symbol, pos.side.value, pnl, reason)

    async def _partial_close(self, pos: ManagedPosition, price: float, qty: float) -> None:
        result = await self.adapter.close_position(pos.symbol, pos.side.value, qty)
        if result is None:
            return
        pnl = self._realized_pnl(pos, price, qty)
        pos.realized_pnl += pnl
        pos.remaining_qty = max(0.0, (pos.remaining_qty or pos.qty) - qty)
        pos.partial_filled = True
        self.risk.record_trade_result(pnl)
        logger.info("PARTIAL %s qty=%s pnl=%.4f", pos.symbol, qty, pnl)

    def _pnl_pct(self, pos: ManagedPosition, price: float) -> float:
        if pos.side == OrderSide.long:
            return (price - pos.entry_price) / pos.entry_price * 100 * pos.leverage
        return (pos.entry_price - price) / pos.entry_price * 100 * pos.leverage

    def _realized_pnl(self, pos: ManagedPosition, price: float, qty: float) -> float:
        if pos.side == OrderSide.long:
            gross = (price - pos.entry_price) * qty
        else:
            gross = (pos.entry_price - price) * qty
        fees = (pos.entry_price + price) * qty * self.fee_pct / 100
        return gross - fees

    def _confirmed_fill(self, order: Optional[Dict[str, Any]]) -> Optional[float]:
        if not order:
            return None
        filled = order.get("filled") or order.get("amount")
        status = str(order.get("status", "")).lower()
        if filled and (status in ("closed", "filled") or order.get("average")):
            return float(filled)
        if status == "rejected":
            return None
        return None

    def _add_pending(self, symbol: str) -> None:
        self._pending_orders.add(symbol)

    def _remove_pending(self, symbol: str) -> None:
        self._pending_orders.discard(symbol)

    def _is_pending(self, symbol: str) -> bool:
        return symbol in self._pending_orders

    def exchange_name(self) -> str:
        return self.adapter.exchange_id.value if hasattr(self.adapter.exchange_id, "value") else str(self.adapter.exchange_id)

    _last_price_cache: Dict[str, float] = field(default_factory=dict)

    async def _fetch_price(self, symbol: str) -> float:
        ticker = await self.adapter.fetch_ticker(symbol)
        price = float(ticker.get("last") or ticker.get("close") or 0)
        self._last_price_cache[symbol] = price
        return price

    # ------------------------------------------------------------------
    def snapshots(self) -> List[PositionSnapshot]:
        out = []
        for pos in self.positions.values():
            if pos.closed:
                continue
            out.append(PositionSnapshot(
                positionId=pos.position_id,
                exchange=pos.exchange,
                symbol=pos.symbol,
                product=pos.product,
                side=pos.side,
                qty=pos.remaining_qty or pos.qty,
                entryPrice=pos.entry_price,
                markPrice=self._last_price_cache.get(pos.symbol, pos.entry_price),
                leverage=pos.leverage,
                stopLoss=pos.stop_loss,
                takeProfit=pos.take_profit,
                trailingActive=pos.trailing_active,
                partialFilled=pos.partial_filled,
                realizedPnl=pos.realized_pnl,
                unrealizedPnl=self._pnl_pct(pos, self._last_price_cache.get(pos.symbol, pos.entry_price)) / 100 * pos.entry_price * (pos.remaining_qty or pos.qty),
                openedAt=datetime.fromtimestamp(pos.opened_at, tz=timezone.utc),
                updatedAt=datetime.fromtimestamp(pos.updated_at, tz=timezone.utc),
            ))
        return out

    # ------------------------------------------------------------------
    async def reconcile(self) -> None:
        """Sync internal state with actual exchange positions; drop ghosts."""
        try:
            remote = await self.adapter.fetch_open_positions()
        except Exception:
            return
        remote_symbols = {p["symbol"] for p in remote}
        for pos in list(self.positions.values()):
            if pos.closed:
                continue
            if pos.symbol not in remote_symbols:
                # position no longer exists on exchange — close record
                pnl = pos.realized_pnl
                self.risk.record_trade_result(pnl)
                pos.closed = True
                logger.info("RECONCILE: %s not on exchange, marking closed", pos.symbol)
                self.positions.pop(pos.position_id, None)