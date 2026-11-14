"""Risk management component.

Independent gatekeeper: position sizing from real equity and contract specs,
daily loss limits, drawdown limits, consecutive-loss protection, leverage and
concurrency caps. Attractive signals never override these restrictions.
"""
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from app.models import RiskSettings

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    day_start_ts: float = 0.0
    day_start_equity: float = 0.0
    day_realized_pnl: float = 0.0
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(self, settings: RiskSettings):
        self.settings = settings
        self.state = RiskState()
        self._roll_day_if_needed(0.0)

    def _now_utc_day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day_if_needed(self, equity: float) -> None:
        today = self._now_utc_day()
        if self.state.day_start_ts == 0.0 or time.strftime("%Y-%m-%d", time.gmtime(self.state.day_start_ts)) != today:
            self.state.day_start_ts = time.time()
            self.state.day_start_equity = equity
            self.state.day_realized_pnl = 0.0
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    def update_equity(self, equity: float) -> None:
        self._roll_day_if_needed(equity)

    def record_trade_result(self, pnl: float) -> None:
        self.state.day_realized_pnl += pnl
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        s = self.settings
        base = self.state.day_start_equity or 1.0
        if self.state.day_realized_pnl <= -base * s.maxDailyLossPct / 100:
            self.state.halted = True
            self.state.halt_reason = "daily_loss_limit"
        if self.state.consecutive_losses >= s.consecutiveLossLimit:
            self.state.halted = True
            self.state.halt_reason = "consecutive_losses"
        dd = (self.state.peak_equity - (base + self.state.day_realized_pnl)) / max(self.state.peak_equity, 1e-9)
        if dd * 100 >= s.maxDrawdownPct:
            self.state.halted = True
            self.state.halt_reason = "max_drawdown"

    def can_open(self, open_positions: int) -> Tuple[bool, str]:
        if self.state.halted:
            return False, self.state.halt_reason
        if open_positions >= self.settings.maxConcurrentPositions:
            return False, "max_positions"
        return True, ""

    def position_size(
        self,
        equity: float,
        price: float,
        stop_loss_pct: float,
        leverage_cap: int,
        contract_min_amount: Optional[float],
        amount_precision: Optional[float],
        taker_fee_pct: float = 0.05,
    ) -> Optional[float]:
        """Risk-based sizing: risk budget = equity * riskPct; notional such that
        stop distance * notional equals the risk budget. Clamped by leverage and
        exchange minimums; rejects rather than exceeding risk."""
        s = self.settings
        if equity <= 0 or price <= 0 or stop_loss_pct <= 0:
            return None
        risk_budget = equity * s.riskPerTradePct / 100.0
        loss_per_unit_notional = stop_loss_pct / 100.0 + 2 * taker_fee_pct / 100.0
        notional = risk_budget / loss_per_unit_notional
        max_notional = equity * min(leverage_cap, s.maxLeverage)
        notional = min(notional, max_notional)
        amount = notional / price
        if contract_min_amount and amount < contract_min_amount:
            return None
        if amount_precision:
            try:
                step = float(amount_precision)
                if step > 0:
                    amount = math.floor(amount / step) * step
            except (TypeError, ValueError):
                pass
        if amount <= 0:
            return None
        return float(amount)

    def stop_and_target_prices(self, side: str, entry: float) -> Dict[str, float]:
        s = self.settings
        if side == "long":
            sl = entry * (1 - s.stopLossPct / 100)
            tp = entry * (1 + s.takeProfitPct / 100)
        else:
            sl = entry * (1 + s.stopLossPct / 100)
            tp = entry * (1 - s.takeProfitPct / 100)
        return {"stop_loss": sl, "take_profit": tp}

    def emergency_halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason
        logger.warning("EMERGENCY HALT: %s", reason)

    def resume(self) -> None:
        self.state.halted = False
        self.state.halt_reason = ""
        self.state.consecutive_losses = 0

    def settings_update(self, s: RiskSettings) -> None:
        self.settings = s