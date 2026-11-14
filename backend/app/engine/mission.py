"""Profit Mission system.

Goal-based capital-growth challenges: starting/current/target capital,
realized vs unrealized profit shown separately, compounding, pause/resume,
daily loss limits, and stop-opening-trades when target reached. Position
sizing never scales with mission progress — it always obeys RiskManager.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MISSION_STATUSES = ("active", "paused", "completed")


class ProfitMission:
    def __init__(self, record: Dict[str, Any], risk: Any):
        self.record = record
        self.risk = risk

    @property
    def id(self) -> str:
        return self.record.get("id", "")

    @property
    def status(self) -> str:
        return self.record.get("status", "active")

    @property
    def starting_capital(self) -> float:
        return float(self.record.get("starting_capital", 0))

    @property
    def current_capital(self) -> float:
        return self.starting_capital + self.realized_profit

    @property
    def target_capital(self) -> float:
        return float(self.record.get("target_capital", 0))

    @property
    def realized_profit(self) -> float:
        return float(self.record.get("realized_profit", 0))

    @property
    def unrealized_profit(self) -> float:
        return float(self.record.get("unrealized_profit", 0))

    @property
    def remaining(self) -> float:
        return max(0.0, self.target_capital - self.current_capital)

    @property
    def progress_pct(self) -> float:
        span = self.target_capital - self.starting_capital
        if span <= 0:
            return 100.0
        return float(min(100.0, max(0.0, (self.current_capital - self.starting_capital) / span * 100)))

    @property
    def compounding(self) -> bool:
        return bool(self.record.get("compounding", True))

    def allows_new_trades(self) -> bool:
        if self.status != "active":
            return False
        return self.current_capital < self.target_capital

    def record_realized(self, pnl: float) -> None:
        self.record["realized_profit"] = self.realized_profit + pnl

    def set_unrealized(self, unrealized: float) -> None:
        self.record["unrealized_profit"] = unrealized

    def check_completion(self) -> bool:
        if self.status == "active" and self.current_capital >= self.target_capital:
            self.record["status"] = "completed"
            self.record["completed_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Mission %s COMPLETED", self.id)
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "startingCapital": self.starting_capital,
            "currentCapital": round(self.current_capital, 4),
            "targetCapital": self.target_capital,
            "realizedProfit": round(self.realized_profit, 4),
            "unrealizedProfit": round(self.unrealized_profit, 4),
            "remaining": round(self.remaining, 4),
            "progressPct": round(self.progress_pct, 2),
            "status": self.status,
            "compounding": self.compounding,
            "startedAt": self.record.get("started_at"),
            "completedAt": self.record.get("completed_at"),
            "allowsNewTrades": self.allows_new_trades(),
        }


class MissionEngine:
    """Manages all missions for the current user."""

    def __init__(self, db, user_id: str, risk: Any):
        self.db = db
        self.user_id = user_id
        self.risk = risk
        self._active: Optional[ProfitMission] = None

    async def load_active(self) -> Optional[ProfitMission]:
        try:
            resp = self.db.table("profit_missions").select("*").eq("user_id", self.user_id).eq("status", "active").limit(1).execute()
            rows = resp.data or []
        except Exception as exc:
            logger.warning("mission load failed: %s", exc)
            return None
        if not rows:
            self._active = None
            return None
        self._active = ProfitMission(rows[0], self.risk)
        return self._active

    @property
    def active(self) -> Optional[ProfitMission]:
        return self._active

    def on_trade_closed(self, pnl: float) -> None:
        m = self.active
        if m is None or m.status != "active":
            return
        m.record_realized(pnl)
        m.check_completion()
        self._persist(m)

    def set_unrealized(self, total_unrealized: float) -> None:
        m = self.active
        if m is not None:
            m.set_unrealized(total_unrealized)

    def allows_new_trades(self) -> bool:
        m = self.active
        if m is None:
            return True
        return m.allows_new_trades()

    def _persist(self, m: ProfitMission) -> None:
        try:
            self.db.table("profit_missions").update({
                "realized_profit": m.realized_profit,
                "status": m.status,
                "completed_at": m.record.get("completed_at"),
            }).eq("id", m.id).execute()
        except Exception as exc:
            logger.warning("mission persist failed: %s", exc)