"""Profit Mission: goal-based capital-growth challenge.

Realized and unrealized profit are tracked separately. A paused or completed
mission blocks new entries (the user starts a new mission to continue). Position
sizing never scales with mission progress - it always obeys the RiskManager.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class MissionEngine:
    def __init__(self, db, user_id: str):
        self.db = db
        self.user_id = user_id
        self.current: Optional[Dict[str, Any]] = None   # most recent mission row

    def refresh(self) -> None:
        try:
            rows = (self.db.table("profit_missions").select("*").eq("user_id", self.user_id)
                    .order("created_at", desc=True).limit(1).execute().data or [])
            self.current = rows[0] if rows else None
        except Exception as exc:
            logger.warning("mission refresh failed: %s", exc)

    def gate(self) -> Tuple[bool, str]:
        """May the engine open new trades under the current mission?"""
        m = self.current
        if m is None:
            return True, ""
        if m["status"] == "paused":
            return False, "mission_paused"
        if m["status"] == "completed":
            return False, "mission_completed"
        capital = float(m["starting_capital"]) + float(m["realized_profit"])
        if capital >= float(m["target_capital"]):
            return False, "mission_target_reached"
        return True, ""

    def on_trade_closed(self, pnl: float) -> None:
        m = self.current
        if m is None or m["status"] != "active":
            return
        m["realized_profit"] = float(m["realized_profit"]) + pnl
        update: Dict[str, Any] = {"realized_profit": m["realized_profit"]}
        if float(m["starting_capital"]) + m["realized_profit"] >= float(m["target_capital"]):
            m["status"] = "completed"
            m["completed_at"] = datetime.now(timezone.utc).isoformat()
            update.update({"status": "completed", "completed_at": m["completed_at"]})
            logger.info("Mission %s COMPLETED", m["id"])
        try:
            self.db.table("profit_missions").update(update).eq("id", m["id"]).execute()
        except Exception as exc:
            logger.warning("mission persist failed: %s", exc)
