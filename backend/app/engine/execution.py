"""Automated execution engine (one per exchange adapter).

Opens and manages positions: sizing from real equity and contract specs,
exchange-confirmed fills, exchange-side protective orders (live), software
stop-loss / take-profit, partial profit, break-even, trailing stop, early exit
on signal reversal, max holding time, and reconciliation with the account.
An order is never treated as filled until the exchange confirms it.
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.engine.risk import RiskManager
from app.models import Opportunity, OrderSide, PositionSnapshot, TradingDecision

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 180      # no immediate re-entry into the same symbol
EARLY_EXIT_SCORE = 0.6      # opposite signal at least this strong closes a trade


@dataclass
class ManagedPosition:
    position_id: str
    exchange: str
    symbol: str
    product: str
    side: OrderSide
    qty: float                   # contracts
    contract_size: float
    entry_price: float
    leverage: int
    stop_loss: float
    take_profit: float
    opened_at: float
    updated_at: float
    mode: str = "paper"
    trailing_active: bool = False
    partial_filled: bool = False
    break_even_set: bool = False
    realized_pnl: float = 0.0    # booked so far (partials), net of fees
    remaining_qty: float = 0.0
    closed: bool = False
    last_price: float = 0.0
    exit_reason: str = ""
    fees: float = 0.0
    protection_ids: List[str] = field(default_factory=list)

    @property
    def open_qty(self) -> float:
        return self.remaining_qty if self.remaining_qty > 0 else self.qty


class ExecutionEngine:
    def __init__(self, adapter: Any, risk: RiskManager,
                 signal_lookup: Optional[Callable[[str, str], Optional[Opportunity]]] = None):
        self.adapter = adapter
        self.risk = risk
        self.signal_lookup = signal_lookup
        self.positions: Dict[str, ManagedPosition] = {}
        self._closed: List[ManagedPosition] = []
        self._busy: set = set()
        self._cooldown: Dict[str, float] = {}
        self._last_price: Dict[str, float] = {}

    # ------------------------------------------------------------------ helpers
    @property
    def exchange_name(self) -> str:
        return self.adapter.exchange_id.value

    @property
    def mode(self) -> str:
        return "paper" if self.adapter.is_paper else "live"

    def open_position_count(self) -> int:
        return sum(1 for p in self.positions.values() if not p.closed)

    def has_position(self, symbol: str) -> bool:
        return any(p.symbol == symbol and not p.closed for p in self.positions.values())

    def drain_closed(self) -> List[ManagedPosition]:
        out, self._closed = self._closed, []
        return out

    def _price_move_pct(self, pos: ManagedPosition, price: float) -> float:
        """Unleveraged price move in the position's favour, in percent."""
        d = (price - pos.entry_price) if pos.side == OrderSide.long else (pos.entry_price - price)
        return d / pos.entry_price * 100

    def _pnl(self, pos: ManagedPosition, price: float, qty: float) -> tuple:
        d = (price - pos.entry_price) if pos.side == OrderSide.long else (pos.entry_price - price)
        gross = d * qty * pos.contract_size
        fees = (pos.entry_price + price) * qty * pos.contract_size * self.risk.settings.takerFeePct / 100
        return gross - fees, fees

    async def _price(self, symbol: str) -> float:
        t = await self.adapter.fetch_ticker(symbol)
        price = float(t.get("last") or t.get("close") or 0)
        if price > 0:
            self._last_price[symbol] = price
        return price

    @staticmethod
    def _filled(order: Optional[Dict[str, Any]]) -> float:
        if not order:
            return 0.0
        status = str(order.get("status", "")).lower()
        filled = float(order.get("filled") or 0)
        if status in ("canceled", "rejected", "expired") and filled <= 0:
            return 0.0
        return filled

    # ------------------------------------------------------------------ entry
    async def try_enter(self, opp: Opportunity, equity: float,
                        open_total: Optional[int] = None) -> Optional[ManagedPosition]:
        sym = opp.symbol
        if sym in self._busy or self.has_position(sym):
            return None
        if time.time() < self._cooldown.get(sym, 0):
            return None
        ok, reason = self.risk.can_open(open_total if open_total is not None else self.open_position_count())
        if not ok:
            logger.info("entry blocked by risk (%s)", reason)
            return None
        ok, reason = self.risk.trade_costs_ok(opp.spreadPct)
        if not ok:
            logger.info("entry blocked (%s): TP does not cover costs for %s", reason, sym)
            return None

        side = OrderSide.long if opp.decision == TradingDecision.LONG else OrderSide.short
        mkt = self.adapter.market(sym) or {}
        csize = float(mkt.get("contractSize") or 1)
        try:
            price = await self._price(sym)
        except Exception as exc:
            logger.warning("price fetch failed %s: %s", sym, exc)
            return None
        if price <= 0:
            return None

        notional = self.risk.notional_for_risk(equity)
        try:
            qty = self.adapter.amount_to_precision(sym, notional / (price * csize))
        except Exception:
            qty = notional / (price * csize)
        min_amt = ((mkt.get("limits") or {}).get("amount") or {}).get("min") or 0
        min_cost = ((mkt.get("limits") or {}).get("cost") or {}).get("min") or 0
        if qty <= 0 or qty < min_amt or qty * price * csize < min_cost:
            logger.info("sizing rejected %s: qty=%s min_amt=%s min_cost=%s (account too small for this contract)",
                        sym, qty, min_amt, min_cost)
            self._cooldown[sym] = time.time() + 120   # do not retry every cycle
            return None

        leverage = max(1, min(self.risk.settings.maxLeverage, 5))
        self._busy.add(sym)
        try:
            await self.adapter.prepare_symbol(sym, leverage)
            order = await self.adapter.create_market_order(sym, "buy" if side == OrderSide.long else "sell", qty)
            order = await self.adapter.confirm_order(order, sym)
        except Exception as exc:
            logger.error("entry order failed %s %s: %s", self.exchange_name, sym, exc)
            self._cooldown[sym] = time.time() + 60
            return None
        finally:
            self._busy.discard(sym)

        filled = self._filled(order)
        if filled <= 0:
            logger.warning("entry not confirmed for %s (status=%s)", sym, (order or {}).get("status"))
            self._cooldown[sym] = time.time() + 60
            return None

        entry = float(order.get("average") or order.get("price") or price)
        levels = self.risk.stop_and_target_prices(side.value, entry)
        now = time.time()
        pos = ManagedPosition(
            position_id=str(uuid.uuid4()), exchange=self.exchange_name, symbol=sym, product=opp.product,
            side=side, qty=filled, contract_size=csize, entry_price=entry, leverage=leverage,
            stop_loss=levels["stop_loss"], take_profit=levels["take_profit"], opened_at=now, updated_at=now,
            mode=self.mode, remaining_qty=filled, last_price=entry)
        pos.protection_ids = await self.adapter.place_protection(sym, side.value, filled, pos.stop_loss, pos.take_profit)
        self.positions[pos.position_id] = pos
        self._cooldown[sym] = now + COOLDOWN_SECONDS
        logger.info("OPEN %s %s %s qty=%s entry=%s sl=%s tp=%s protected=%s", self.mode, side.value.upper(), sym,
                    filled, entry, round(pos.stop_loss, 6), round(pos.take_profit, 6), bool(pos.protection_ids))
        return pos

    # ------------------------------------------------------------------ management
    async def manage(self) -> None:
        for pos in list(self.positions.values()):
            if pos.closed:
                continue
            try:
                price = await self._price(pos.symbol)
            except Exception:
                continue
            if price <= 0:
                continue
            pos.updated_at, pos.last_price = time.time(), price
            s = self.risk.settings
            move = self._price_move_pct(pos, price)
            long = pos.side == OrderSide.long

            if (time.time() - pos.opened_at) / 60 >= s.maxHoldingMinutes:
                await self._close(pos, price, "max_holding_time")
                continue
            if (long and price <= pos.stop_loss) or (not long and price >= pos.stop_loss):
                await self._close(pos, price, "stop_loss" if not pos.break_even_set else "break_even_or_trailing_stop")
                continue
            if (long and price >= pos.take_profit) or (not long and price <= pos.take_profit):
                await self._close(pos, price, "take_profit")
                continue

            # early exit: a strong opposite signal on this market
            if self.signal_lookup:
                sig = self.signal_lookup(pos.exchange, pos.symbol)
                if sig and sig.score >= EARLY_EXIT_SCORE and (
                        (long and sig.decision == TradingDecision.SHORT) or
                        (not long and sig.decision == TradingDecision.LONG)):
                    await self._close(pos, price, "signal_reversal")
                    continue

            # break-even once half of the take-profit distance is reached
            if not pos.break_even_set and move >= s.takeProfitPct * 0.5:
                cost_buffer = 2 * s.takerFeePct / 100
                pos.stop_loss = pos.entry_price * (1 + cost_buffer) if long else pos.entry_price * (1 - cost_buffer)
                pos.break_even_set = True
            # partial profit at 70% of target
            if not pos.partial_filled and s.partialTakeProfitPct > 0 and move >= s.takeProfitPct * 0.7:
                await self._partial_close(pos, price, pos.open_qty * s.partialTakeProfitPct / 100)
                pos.trailing_active = True
            if pos.trailing_active:
                trail = s.trailingStopPct / 100
                new_sl = price * (1 - trail) if long else price * (1 + trail)
                if (long and new_sl > pos.stop_loss) or (not long and new_sl < pos.stop_loss):
                    pos.stop_loss = new_sl

    async def _close(self, pos: ManagedPosition, price: float, reason: str) -> bool:
        qty = pos.open_qty
        if pos.protection_ids:
            await self.adapter.cancel_orders(pos.symbol, pos.protection_ids)
            pos.protection_ids = []
        order = await self.adapter.close_position(pos.symbol, pos.side.value, qty)
        if order is None or self._filled(order) <= 0:
            logger.error("close failed for %s - will retry next cycle", pos.symbol)
            return False
        exit_price = float(order.get("average") or order.get("price") or price)
        pnl, fees = self._pnl(pos, exit_price, qty)
        pos.realized_pnl += pnl
        pos.fees += fees
        pos.closed, pos.last_price, pos.exit_reason = True, exit_price, reason
        self.risk.record_trade_result(pos.realized_pnl)
        self._closed.append(self.positions.pop(pos.position_id))
        self._cooldown[pos.symbol] = time.time() + COOLDOWN_SECONDS
        logger.info("CLOSE %s %s pnl=%.4f reason=%s", pos.mode, pos.symbol, pos.realized_pnl, reason)
        return True

    async def _partial_close(self, pos: ManagedPosition, price: float, qty: float) -> None:
        try:
            qty = self.adapter.amount_to_precision(pos.symbol, qty)
        except Exception:
            pass
        if qty <= 0 or qty >= pos.open_qty:
            pos.partial_filled = True       # too small to split; trailing stop still applies
            return
        order = await self.adapter.close_position(pos.symbol, pos.side.value, qty)
        if order is None or self._filled(order) <= 0:
            return
        exit_price = float(order.get("average") or order.get("price") or price)
        pnl, fees = self._pnl(pos, exit_price, qty)
        pos.realized_pnl += pnl
        pos.fees += fees
        pos.remaining_qty = pos.open_qty - qty
        pos.partial_filled = True
        logger.info("PARTIAL %s %s qty=%s pnl=%.4f", pos.mode, pos.symbol, qty, pnl)

    async def close_all(self, reason: str = "manual_close_all") -> int:
        closed = 0
        for pos in list(self.positions.values()):
            if pos.closed:
                continue
            try:
                price = await self._price(pos.symbol)
            except Exception:
                price = pos.last_price or pos.entry_price
            if await self._close(pos, price, reason):
                closed += 1
        return closed

    # ------------------------------------------------------------------ reconciliation
    async def reconcile(self, adopt: bool = True) -> None:
        """Keep internal state identical to the real account: drop positions
        that no longer exist (closed by exchange-side SL/TP or manually) and
        adopt positions that exist but are unknown (e.g. after a restart)."""
        try:
            remote = await self.adapter.fetch_open_positions()
        except Exception as exc:
            logger.warning("reconcile fetch failed on %s: %s", self.exchange_name, exc)
            return
        remote_by_sym = {p["symbol"]: p for p in remote}
        for pos in list(self.positions.values()):
            if pos.closed or pos.symbol in self._busy:
                continue
            if pos.symbol not in remote_by_sym:
                price = self._last_price.get(pos.symbol, pos.entry_price)
                pnl, fees = self._pnl(pos, price, pos.open_qty)
                pos.realized_pnl += pnl
                pos.fees += fees
                pos.closed, pos.last_price, pos.exit_reason = True, price, "closed_on_exchange"
                self.risk.record_trade_result(pos.realized_pnl)
                self._closed.append(self.positions.pop(pos.position_id))
                logger.info("RECONCILE: %s no longer open on exchange; recorded as closed", pos.symbol)
        if not adopt:
            return
        for sym, r in remote_by_sym.items():
            if self.has_position(sym) or sym in self._busy or r["entry"] <= 0:
                continue
            side = OrderSide.long if r["side"] == "long" else OrderSide.short
            mkt = self.adapter.market(sym) or {}
            levels = self.risk.stop_and_target_prices(side.value, r["entry"])
            now = time.time()
            pos = ManagedPosition(
                position_id=str(uuid.uuid4()), exchange=self.exchange_name, symbol=sym, product="futures",
                side=side, qty=r["contracts"], contract_size=float(mkt.get("contractSize") or 1),
                entry_price=r["entry"], leverage=r["leverage"], stop_loss=levels["stop_loss"],
                take_profit=levels["take_profit"], opened_at=now, updated_at=now, mode=self.mode,
                remaining_qty=r["contracts"], last_price=r["mark"] or r["entry"])
            self.positions[pos.position_id] = pos
            logger.warning("RECONCILE: adopted untracked %s position %s on %s", side.value, sym, self.exchange_name)

    # ------------------------------------------------------------------ views
    def snapshots(self) -> List[PositionSnapshot]:
        out: List[PositionSnapshot] = []
        for pos in self.positions.values():
            if pos.closed:
                continue
            mark = self._last_price.get(pos.symbol, pos.entry_price)
            qty = pos.open_qty
            diff = (mark - pos.entry_price) if pos.side == OrderSide.long else (pos.entry_price - mark)
            out.append(PositionSnapshot(
                positionId=pos.position_id, exchange=pos.exchange, symbol=pos.symbol, product=pos.product,
                side=pos.side, qty=qty, entryPrice=pos.entry_price, markPrice=mark, leverage=pos.leverage,
                stopLoss=pos.stop_loss, takeProfit=pos.take_profit, trailingActive=pos.trailing_active,
                partialFilled=pos.partial_filled, protectedOnExchange=bool(pos.protection_ids), mode=pos.mode,
                realizedPnl=pos.realized_pnl, unrealizedPnl=diff * qty * pos.contract_size,
                openedAt=datetime.fromtimestamp(pos.opened_at, tz=timezone.utc),
                updatedAt=datetime.fromtimestamp(pos.updated_at, tz=timezone.utc)))
        return out
