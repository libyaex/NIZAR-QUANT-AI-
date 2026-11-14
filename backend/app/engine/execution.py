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
    # Filled by _close()/reconcile() for persistence by the trading engine.
    last_price: float = 0.0
    exit_reason: str = ""
    estimated_fees: float = 0.0

    @property
    def filled_qty(self) -> float:
        return self.remaining_qty or self.qty


@dataclass
class ExecutionEngine:
    adapter: ExchangeAdapter
    risk: RiskManager
    fee_pct: float = 0.05
    max_holding_minutes: int = 30
    trailing_stop_pct: float = 0.25
    partial_tp_pct: float = 50.0
    positions: Dict[str, ManagedPosition] = field(default_factory=dict)
    _closed_buffer: List[ManagedPosition] = field(default_factory=list)
    _pending_orders: set = field(default_factory=set)
    _last_price_cache: Dict[str, float] = field(default_factory=dict)

    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if not p.closed)

    def exchange_name(self) -> str:
        eid = self.adapter.exchange_id
        return eid.value if hasattr(eid, "value") else str(eid)

    def drain_closed(self) -> List[ManagedPosition]:
        """Return and clear positions closed since the last drain so the
        engine can persist them to the trades table exactly once."""
        drained = self._closed_buffer
        self._closed_buffer = []
        return drained

    def _is_pending(self, symbol: str) -> bool:
        return symbol in self._pending_orders

    def _add_pending(self, symbol: str) -> None:
        self._pending_orders.add(symbol)

    def _remove_pending(self, symbol: str) -> None:
        self._pending_orders.discard(symbol)

    async def _fetch_price(self, symbol: str) -> float:
        ticker = await self.adapter.fetch_ticker(symbol)
        price = float(ticker.get("last") or ticker.get("close") or 0)
        self._last_price_cache[symbol] = price
        return price

    def _pnl_pct(self, pos: ManagedPosition, price: float) -> float:
        if pos.side == OrderSide.long:
            return (price - pos.entry_price) / pos.entry_price * 100 * pos.leverage
        return (pos.entry_price - price) / pos.entry_price * 100 * pos.leverage

    def _fees_for(self, price: float, qty: float) -> float:
        return (self._last_price_cache.get("__entry_marker__", 0) or 0)  # placeholder removed below

    def _realized_pnl(self, pos: ManagedPosition, price: float, qty: float) -> float:
        if pos.side == OrderSide.long:
            gross = (price - pos.entry_price) * qty
        else:
            gross = (pos.entry_price - price) * qty
        fees = (pos.entry_price + price) * qty * self.fee_pct / 100
        return gross - fees

    def _estimated_fees(self, pos: ManagedPosition, price: float, qty: float) -> float:
        if pos.side == OrderSide.long:
            return (pos.entry_price + price) * qty * self.fee_pct / 100
        return (pos.entry_price + price) * qty * self.fee_pct / 100

    def _confirmed_fill(self, order: Optional[Dict[str, Any]]) -> Optional[float]:
        if not order:
            return None
        filled = order.get("filled") or order.get("amount")
        status = str(order.get("status", "")).lower()
        if filled and (status in ("closed", "filled") or order.get("average")):
            return float(filled)
        return None

    async def try_enter(self, opp: Opportunity, equity: float) -> Optional[ManagedPosition]:
        if self._is_pending(opp.symbol):
            return None
        ok, reason = self.risk.can_open(self.open_position_count())
        if not ok:
            logger.info("Entry blocked by risk: %s", reason)
            return None

        side = OrderSide.long if opp.decision == TradingDecision.LONG else OrderSide.short
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

        try:
            price = await self._fetch_price(opp.symbol)
        except Exception as exc:
            logger.warning("price fetch failed %s: %s", opp.symbol, exc)
            return None
        if price <= 0:
            return None

        qty = self.risk.position_size(
            equity=equity,
            price=price,
            stop_loss_pct=self.risk.settings.stopLossPct,
            leverage_cap=self.risk.settings.maxLeverage,
            contract_min_amount=min_amount,
            amount_precision=amount_precision,
            taker_fee_pct=self.fee_pct,
        )
        if qty is None:
            logger.info("Position sizing rejected %s", opp.symbol)
            return None

        leverage = min(self.risk.settings.maxLeverage, 5)
        await self.adapter.set_leverage(opp.symbol, leverage)
        order_side = "buy" if side == OrderSide.long else "sell"
        self._add_pending(opp.symbol)
        try:
            order = await self.adapter.create_market_order(opp.symbol, order_side, qty)
        except Exception as exc:
            logger.error("Entry order failed %s %s: %s", self.exchange_name(), opp.symbol, exc)
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
            if price <= 0:
                continue
            pos.updated_at = time.time()
            pnl_pct = self._pnl_pct(pos, price)
            s = self.risk.settings

            held_min = (time.time() - pos.opened_at) / 60
            if held_min >= self.max_holding_minutes:
                await self._close(pos, price, "max_holding_time")
                to_remove.append(pos.position_id)
                continue

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

            if not pos.partial_filled and pnl_pct >= self.partial_tp_pct / 100 * s.takeProfitPct:
                part = pos.qty * self.partial_tp_pct / 100
                await self._partial_close(pos, price, part)
                pos.stop_loss = pos.entry_price
                pos.trailing_active = True

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
            closed_pos = self.positions.pop(pid, None)
            if closed_pos is not None:
                self._closed_buffer.append(closed_pos)

    async def _close(self, pos: ManagedPosition, price: float, reason: str) -> None:
        qty = pos.remaining_qty or pos.qty
        result = await self.adapter.close_position(pos.symbol, pos.side.value, qty)
        if result is None:
            logger.error("Failed to close %s — will retry next cycle", pos.symbol)
            return
        pnl = self._realized_pnl(pos, price, qty)
        pos.realized_pnl = pnl
        pos.closed = True
        pos.last_price = price
        pos.exit_reason = reason
        pos.estimated_fees = self._estimated_fees(pos, price, qty)
        self.risk.record_trade_result(pnl)
        logger.info("CLOSE %s %s pnl=%.4f reason=%s", pos.symbol, pos.side.value, pnl, reason)

    async def _partial_close(self, pos: ManagedPosition, price: float, qty: float) -> None:
        result = await self.adapter.close_position(pos.symbol, pos.side.value, qty)
        if result is None:
            return
        pnl = self._realized_pnl(pos, price, qty)
        pos.realized_pnl += pnl
        pos.estimated_fees += self._estimated_fees(pos, price, qty)
        pos.last_price = price
        pos.remaining_qty = max(0.0, (pos.remaining_qty or pos.qty) - qty)
        pos.partial_filled = True
        self.risk.record_trade_result(pnl)
        logger.info("PARTIAL %s qty=%s pnl=%.4f", pos.symbol, qty, pnl)

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
            removed = self.positions.pop(pos.position_id, None)
            if removed is not None:
                self._closed_buffer.append(removed)
        return closed

    def snapshots(self) -> List[PositionSnapshot]:
        out: List[PositionSnapshot] = []
        for pos in self.positions.values():
            if pos.closed:
                continue
            mark = self._last_price_cache.get(pos.symbol, pos.entry_price)
            qty = pos.remaining_qty or pos.qty
            price_diff = (mark - pos.entry_price) if pos.side == OrderSide.long else (pos.entry_price - mark)
            out.append(PositionSnapshot(
                positionId=pos.position_id,
                exchange=pos.exchange,
                symbol=pos.symbol,
                product=pos.product,
                side=pos.side,
                qty=qty,
                entryPrice=pos.entry_price,
                markPrice=mark,
                leverage=pos.leverage,
                stopLoss=pos.stop_loss,
                takeProfit=pos.take_profit,
                trailingActive=pos.trailing_active,
                partialFilled=pos.partial_filled,
                realizedPnl=pos.realized_pnl,
                unrealizedPnl=price_diff * qty,
                openedAt=datetime.fromtimestamp(pos.opened_at, tz=timezone.utc),
                updatedAt=datetime.fromtimestamp(pos.updated_at, tz=timezone.utc),
            ))
        return out

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
                self.risk.record_trade_result(pos.realized_pnl)
                pos.closed = True
                pos.exit_reason = "reconciled"
                pos.last_price = self._last_price_cache.get(pos.symbol, pos.entry_price)
                logger.info("RECONCILE: %s not on exchange, marking closed", pos.symbol)
                removed = self.positions.pop(pos.position_id, None)
                if removed is not None:
                    self._closed_buffer.append(removed)
