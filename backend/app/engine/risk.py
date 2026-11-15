"""Risk management: the independent gatekeeper.

Position sizing from real equity, fees and contract specs; daily-loss,
drawdown and consecutive-loss protection; leverage and concurrency caps.
No signal, however attractive, can override these checks.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Tuple

from app.models import RiskSettings

logger = logging.getLogger(__name__)

# Halts that only the user may clear (explicitly), vs. ones that clear by themselves.
SELF_CLEARING = {"daily_loss_limit"}      # clears when the UTC day rolls over
USER_CLEARABLE_ON_START = {"user_halt", "consecutive_losses"}


@dataclass
class RiskState:
    day: str = ""
    day_start_equity: float = 0.0
    day_realized_pnl: float = 0.0
    peak_equity: float = 0.0
    equity: float = 0.0
    consecutive_losses: int = 0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(self, settings: RiskSettings):
        self.settings = settings
        self.state = RiskState()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ equity tracking
    def update_equity(self, equity: float) -> None:
        if equity <= 0:
            return
        st = self.state
        st.equity = equity
        today = self._today()
        if st.day != today:
            st.day, st.day_start_equity, st.day_realized_pnl = today, equity, 0.0
            if st.halt_reason in SELF_CLEARING:
                st.halted, st.halt_reason = False, ""
        if st.day_start_equity <= 0:
            st.day_start_equity = equity
        st.peak_equity = max(st.peak_equity, equity)
        dd = (st.peak_equity - equity) / st.peak_equity * 100 if st.peak_equity else 0.0
        if dd >= self.settings.maxDrawdownPct and not st.halted:
            self._halt("max_drawdown")

    def reset_baseline(self, equity: float) -> None:
        """Call when the account changes (paper <-> live)."""
        self.state = RiskState()
        self.update_equity(equity)

    def record_trade_result(self, pnl: float) -> None:
        st, s = self.state, self.settings
        st.day_realized_pnl += pnl
        st.consecutive_losses = st.consecutive_losses + 1 if pnl < 0 else 0
        base = st.day_start_equity or st.equity or 1.0
        if st.day_realized_pnl <= -base * s.maxDailyLossPct / 100:
            self._halt("daily_loss_limit")
        elif st.consecutive_losses >= s.consecutiveLossLimit:
            self._halt("consecutive_losses")

    def _halt(self, reason: str) -> None:
        self.state.halted, self.state.halt_reason = True, reason
        logger.warning("RISK HALT: %s", reason)

    # ------------------------------------------------------------------ gates
    def can_open(self, open_positions: int) -> Tuple[bool, str]:
        if self.state.halted:
            return False, self.state.halt_reason
        if open_positions >= self.settings.maxConcurrentPositions:
            return False, "max_positions"
        return True, ""

    def trade_costs_ok(self, spread_pct: float) -> Tuple[bool, str]:
        """Take-profit must clearly exceed round-trip costs."""
        cost = 2 * self.settings.takerFeePct + spread_pct
        if self.settings.takeProfitPct < cost * 1.5:
            return False, "take_profit_below_costs"
        return True, ""

    def notional_for_risk(self, equity: float) -> float:
        """Notional (USDT) such that hitting the stop loses riskPerTradePct of
        equity including round-trip fees, capped by the leverage limit."""
        s = self.settings
        if equity <= 0:
            return 0.0
        loss_per_notional = s.stopLossPct / 100 + 2 * s.takerFeePct / 100
        return min(equity * s.riskPerTradePct / 100 / loss_per_notional, equity * s.maxLeverage)

    def stop_and_target_prices(self, side: str, entry: float) -> Dict[str, float]:
        s = self.settings
        if side == "long":
            return {"stop_loss": entry * (1 - s.stopLossPct / 100), "take_profit": entry * (1 + s.takeProfitPct / 100)}
        return {"stop_loss": entry * (1 + s.stopLossPct / 100), "take_profit": entry * (1 - s.takeProfitPct / 100)}

    # ------------------------------------------------------------------ controls
    def emergency_halt(self, reason: str) -> None:
        self._halt(reason)

    def resume(self) -> None:
        """Called on START TRADING. Clears only halts the user is allowed to
        override; daily-loss and drawdown protections stay in force."""
        if self.state.halt_reason in USER_CLEARABLE_ON_START:
            self.state.halted, self.state.halt_reason = False, ""
            self.state.consecutive_losses = 0

    def reset(self) -> None:
        """Explicit user action: clear every halt."""
        self.state.halted, self.state.halt_reason = False, ""
        self.state.consecutive_losses = 0
        self.state.peak_equity = self.state.equity

    def settings_update(self, s: RiskSettings) -> None:
        self.settings = s
