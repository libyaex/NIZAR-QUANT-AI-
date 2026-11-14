"""Trading state persistence and trade-recording helpers.

The engine keeps runtime state in memory; this service persists closed
trades and audit events to Supabase so history and performance are
always built from real execution data.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class TradeRecorder:
    """Writes closed trades into the trades table with fees and reasons."""

    def __init__(self, db, user_id: str):
        self.db = db
        self.user_id = user_id

    def record(self, exchange: str, symbol: str, product: str, side: str,
               qty: float, entry_price: float, exit_price: float,
               realized_pnl: float, fees: float, notes: Optional[str] = None) -> None:
        try:
            self.db.table("trades").insert({
                "user_id": self.user_id,
                "exchange": exchange,
                "symbol": symbol,
                "product": product,
                "side": side,
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "realized_pnl": realized_pnl,
                "fees": fees,
                "status": "closed",
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "notes": notes,
            }).execute()
        except Exception as exc:
            logger.warning("trade record failed %s: %s", symbol, exc)

    def audit(self, event: str, detail: dict) -> None:
        try:
            self.db.table("audit_log").insert({
                "user_id": self.user_id,
                "event": event,
                "detail": detail,
            }).execute()
        except Exception as exc:
            logger.warning("audit write failed: %s", exc)