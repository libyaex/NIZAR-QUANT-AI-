"""HTTP API.

Public (no login): market data, scanner, charts, diagnostics - so the app
shows live data immediately. Everything that touches an account, settings or
trading controls requires a signed-in user.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import AuthUser, current_user
from app.config import get_settings
from app.engine.mission import MissionEngine
from app.engine.runtime import engine_runtime
from app.models import (EngineStatusOut, ExchangeConfigIn, ExchangeStatus, MissionIn, MissionUpdate,
                        PerformanceOut, PositionSnapshot, RiskSettings, ScannerConfig, StartStopIn,
                        TradingDecision)
from app.services.supabase_client import db_ready, get_supabase

logger = logging.getLogger(__name__)
router = APIRouter()


def _db():
    db = get_supabase(get_settings())
    if not db_ready(db):
        raise HTTPException(503, "Database is not configured on the server (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    return db


def _engine():
    try:
        return engine_runtime.engine
    except RuntimeError:
        raise HTTPException(503, "Engine is starting - retry in a few seconds")


# ======================================================================= public
@router.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/diagnostics")
async def diagnostics():
    s = get_settings()
    e = _engine()
    return {
        "version": "2.0.0",
        "uptimeSeconds": int(time.time() - e.started_at),
        "supabaseConfigured": bool(s.supabase_url and s.supabase_service_role_key),
        "vaultConfigured": bool(s.credential_encryption_key),
        "exchanges": e.hub.status(),
    }


@router.get("/market")
async def market(limit: int = 10):
    e = _engine()
    opps = e.hub.opportunities()[:limit]
    return {
        "exchanges": e.hub.status(),
        "opportunities": [o.model_dump(mode="json") for o in opps],
        "scanned": sum(s["scanned"] for s in e.hub.status()),
    }


@router.get("/scanner")
async def scanner(limit: int = 100, all: bool = True, exchange: Optional[str] = None):
    e = _engine()
    rows = e.hub.opportunities(include_hold=all)
    if exchange:
        rows = [o for o in rows if o.exchange == exchange]
    return {"opportunities": [o.model_dump(mode="json") for o in rows[:limit]], "exchanges": e.hub.status()}


@router.get("/chart")
async def chart(exchange: str, symbol: str, tf: str = "1m"):
    e = _engine()
    try:
        return await e.hub.chart(exchange, symbol, tf)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Market data unavailable: {str(exc)[:200]}")


# ======================================================================= account
@router.get("/status", response_model=EngineStatusOut)
async def status(user: AuthUser = Depends(current_user)):
    return _engine().status()


@router.post("/trading/ctl", response_model=EngineStatusOut)
async def trading_control(body: StartStopIn, user: AuthUser = Depends(current_user)):
    if body.action not in ("start", "stop", "halt"):
        raise HTTPException(400, "action must be start|stop|halt")
    _db()
    e = _engine()
    try:
        await e.set_trading(user.id, body.action)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    await e.refresh_equity()
    return e.status()


@router.post("/trading/close-all")
async def close_all(user: AuthUser = Depends(current_user)):
    return {"closed": await _engine().close_all_positions()}


@router.post("/risk/reset")
async def risk_reset(user: AuthUser = Depends(current_user)):
    e = _engine()
    e.reset_risk(user.id)
    return e.status()


@router.post("/paper/reset")
async def paper_reset(user: AuthUser = Depends(current_user)):
    e = _engine()
    if e.open_total():
        raise HTTPException(409, "Close open positions first")
    e.paper.reset(e.risk.settings.paperBalance)
    e._baseline_pending = True
    await e.refresh_equity()
    return e.status()


@router.get("/positions", response_model=List[PositionSnapshot])
async def positions(user: AuthUser = Depends(current_user)):
    return _engine().snapshots()


# ----------------------------------------------------------------------- dashboard
def _mode_rows(rows: List[dict], mode: str) -> List[dict]:
    def row_mode(r: dict) -> str:
        return "paper" if str(r.get("notes") or "").startswith("paper|") else "live"
    return [r for r in rows if row_mode(r) == mode]


def _mission_to_api(row: Dict, unrealized: float = 0.0) -> Dict:
    starting, target = float(row.get("starting_capital", 0)), float(row.get("target_capital", 0))
    realized = float(row.get("realized_profit", 0))
    current = starting + realized
    span = target - starting
    progress = 0.0 if span <= 0 else min(100.0, max(0.0, (current - starting) / span * 100))
    status = row.get("status", "active")
    return {
        "id": row.get("id"), "startingCapital": starting, "currentCapital": round(current, 4),
        "targetCapital": target, "realizedProfit": round(realized, 4),
        "unrealizedProfit": round(unrealized if status == "active" else 0.0, 4),
        "remaining": round(max(0.0, target - current), 4), "progressPct": round(progress, 2),
        "status": status, "compounding": bool(row.get("compounding", True)),
        "startedAt": row.get("started_at") or row.get("created_at"), "completedAt": row.get("completed_at"),
        "allowsNewTrades": status == "active" and current < target,
    }


def _latest_mission(db, user_id: str) -> Optional[Dict]:
    rows = db.table("profit_missions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute().data or []
    return rows[0] if rows else None


@router.get("/dashboard")
async def dashboard(user: AuthUser = Depends(current_user)):
    e = _engine()
    db = _db()
    mode = e.mode.value
    trades = db.table("trades").select("*").eq("user_id", user.id).eq("status", "closed").order("created_at").execute().data or []
    perf = compute_performance(_mode_rows(trades, mode))
    m = _latest_mission(db, user.id)
    return {
        "status": e.status().model_dump(mode="json"),
        "positions": [p.model_dump(mode="json") for p in e.snapshots()],
        "unrealized": round(e.total_unrealized(), 4),
        "today": {"pnl": perf.todayPnl, "trades": len([r for r in _mode_rows(trades, mode)
                                                        if str(r.get("closed_at") or "")[:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d")])},
        "performance": perf.model_dump(mode="json"),
        "mission": _mission_to_api(m, e.total_unrealized()) if m else None,
        "opportunities": [o.model_dump(mode="json") for o in e.hub.opportunities()[:5]],
        "exchanges": e.hub.status(),
    }


# ----------------------------------------------------------------------- exchanges
@router.get("/exchanges", response_model=List[ExchangeStatus])
async def list_exchanges(user: AuthUser = Depends(current_user)):
    e = _engine()
    rows = _db().table("exchange_configs").select("*").eq("user_id", user.id).execute().data or []
    if rows and any(r["id"] not in e.live_status for r in rows):
        await e.load_user_exchanges(user.id)
    out = []
    for row in rows:
        st = e.live_status.get(row["id"], {})
        adapter = e.live_adapters.get(row["id"])
        out.append(ExchangeStatus(
            id=row["id"], exchange=row["exchange"], label=row.get("label", "default"),
            product=row.get("product", "futures"), testnet=bool(row.get("testnet", False)),
            connected=adapter is not None,
            markets=len(adapter.client.markets or {}) if adapter else 0,
            lastError=st.get("error") or None, createdAt=row.get("created_at")))
    return out


@router.post("/exchanges", response_model=ExchangeStatus)
async def connect_exchange(body: ExchangeConfigIn, user: AuthUser = Depends(current_user)):
    e = _engine()
    db = _db()
    try:
        vault = e.vault()
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    row = {
        "user_id": user.id, "exchange": body.exchange.value, "label": body.label,
        "product": body.product.value, "testnet": body.testnet,
        "api_key_enc": vault.encrypt(body.apiKey.strip()), "secret_enc": vault.encrypt(body.secret.strip()),
        "password_enc": vault.encrypt(body.password.strip()) if body.password else None,
    }
    created = (db.table("exchange_configs").insert(row).execute().data or [None])[0]
    if not created:
        raise HTTPException(500, "Could not save exchange configuration")
    await e.load_user_exchanges(user.id)
    st = e.live_status.get(created["id"], {})
    adapter = e.live_adapters.get(created["id"])
    return ExchangeStatus(
        id=created["id"], exchange=created["exchange"], label=created["label"], product=created["product"],
        testnet=bool(created.get("testnet", False)), connected=adapter is not None,
        markets=len(adapter.client.markets or {}) if adapter else 0,
        lastError=st.get("error") or None, createdAt=created.get("created_at"))


@router.delete("/exchanges/{cfg_id}")
async def disconnect_exchange(cfg_id: str, user: AuthUser = Depends(current_user)):
    db = _db()
    if not (db.table("exchange_configs").select("id").eq("id", cfg_id).eq("user_id", user.id).execute().data or []):
        raise HTTPException(404, "Exchange config not found")
    try:
        await _engine().remove_exchange(cfg_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.table("exchange_configs").delete().eq("id", cfg_id).eq("user_id", user.id).execute()
    return {"removed": True}


# ----------------------------------------------------------------------- settings
@router.get("/settings/risk", response_model=RiskSettings)
async def get_risk(user: AuthUser = Depends(current_user)):
    return _engine().risk.settings


@router.put("/settings/risk", response_model=RiskSettings)
async def put_risk(body: RiskSettings, user: AuthUser = Depends(current_user)):
    _db()
    try:
        _engine().apply_settings(user.id, risk=body)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return body


@router.get("/settings/scanner", response_model=ScannerConfig)
async def get_scanner_cfg(user: AuthUser = Depends(current_user)):
    return _engine().scanner_config


@router.put("/settings/scanner", response_model=ScannerConfig)
async def put_scanner_cfg(body: ScannerConfig, user: AuthUser = Depends(current_user)):
    _db()
    _engine().apply_settings(user.id, scanner=body)
    return body


# ----------------------------------------------------------------------- missions
@router.get("/missions")
async def list_missions(user: AuthUser = Depends(current_user)):
    e = _engine()
    rows = _db().table("profit_missions").select("*").eq("user_id", user.id).order("created_at", desc=True).execute().data or []
    unreal = e.total_unrealized()
    return {"missions": [_mission_to_api(r, unreal if i == 0 else 0.0) for i, r in enumerate(rows)]}


@router.post("/missions")
async def create_mission(body: MissionIn, user: AuthUser = Depends(current_user)):
    if body.startingCapital <= 0:
        raise HTTPException(400, "Starting capital must be positive")
    if body.targetCapital <= body.startingCapital:
        raise HTTPException(400, "Target must exceed starting capital")
    db = _db()
    db.table("profit_missions").update({"status": "paused"}).eq("user_id", user.id).eq("status", "active").execute()
    created = (db.table("profit_missions").insert({
        "user_id": user.id, "starting_capital": body.startingCapital, "target_capital": body.targetCapital,
        "realized_profit": 0.0, "unrealized_profit": 0.0, "status": "active", "compounding": body.compounding,
    }).execute().data or [None])[0]
    if not created:
        raise HTTPException(500, "Could not create mission")
    e = _engine()
    e.missions.setdefault(user.id, MissionEngine(db, user.id)).refresh()
    return _mission_to_api(created)


@router.put("/missions/{mission_id}")
async def update_mission(mission_id: str, body: MissionUpdate, user: AuthUser = Depends(current_user)):
    db = _db()
    updates: Dict[str, Any] = {}
    if body.status is not None:
        if body.status not in ("active", "paused"):
            raise HTTPException(400, "status must be active or paused")
        updates["status"] = body.status
    if body.compounding is not None:
        updates["compounding"] = body.compounding
    if not updates:
        raise HTTPException(400, "nothing to update")
    own = db.table("profit_missions").select("*").eq("id", mission_id).eq("user_id", user.id).execute().data or []
    if not own:
        raise HTTPException(404, "Mission not found")
    if own[0]["status"] == "completed" and body.status == "active":
        raise HTTPException(409, "A completed mission cannot be resumed - start a new mission")
    db.table("profit_missions").update(updates).eq("id", mission_id).eq("user_id", user.id).execute()
    row = (db.table("profit_missions").select("*").eq("id", mission_id).execute().data or [own[0]])[0]
    e = _engine()
    if user.id in e.missions:
        e.missions[user.id].refresh()
    return _mission_to_api(row, e.total_unrealized())


# ----------------------------------------------------------------------- history
@router.get("/trades")
async def trades(limit: int = 100, mode: Optional[str] = None, user: AuthUser = Depends(current_user)):
    rows = _db().table("trades").select("*").eq("user_id", user.id).order("created_at", desc=True).limit(500).execute().data or []
    if mode in ("paper", "live"):
        rows = _mode_rows(rows, mode)
    return {"trades": rows[:limit]}


@router.get("/performance", response_model=PerformanceOut)
async def performance(mode: Optional[str] = None, user: AuthUser = Depends(current_user)):
    rows = _db().table("trades").select("*").eq("user_id", user.id).eq("status", "closed").order("created_at").execute().data or []
    return compute_performance(_mode_rows(rows, mode or _engine().mode.value))


def _pnl(r: dict) -> float:
    return float(r.get("realized_pnl") or 0)


def _closed_dt(r: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(r.get("closed_at") or r.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_performance(rows: List[dict]) -> PerformanceOut:
    """Statistics from real recorded trades only - never synthetic numbers."""
    rows = sorted(rows, key=lambda r: str(r.get("closed_at") or r.get("created_at")))
    wins = [r for r in rows if _pnl(r) > 0]
    losses = [r for r in rows if _pnl(r) <= 0]
    gross_win = sum(_pnl(r) for r in wins)
    gross_loss = abs(sum(_pnl(r) for r in losses))
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    for r in rows:
        cum += _pnl(r)
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        curve.append({"t": str(r.get("closed_at") or r.get("created_at")), "pnl": round(cum, 4)})
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    daily: Dict[str, float] = {}
    weekly: Dict[str, float] = {}
    for r in rows:
        d = _closed_dt(r)
        if d is None:
            continue
        daily[d.strftime("%Y-%m-%d")] = daily.get(d.strftime("%Y-%m-%d"), 0.0) + _pnl(r)
        wk = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
        weekly[wk] = weekly.get(wk, 0.0) + _pnl(r)
    week_ago = now - timedelta(days=7)

    def summarize(sub: List[dict]) -> Dict[str, Any]:
        w = sum(1 for r in sub if _pnl(r) > 0)
        return {"trades": len(sub), "netPnl": round(sum(_pnl(r) for r in sub), 4),
                "winRate": round(w / len(sub) * 100, 2) if sub else 0.0}

    return PerformanceOut(
        totalTrades=len(rows), wins=len(wins), losses=len(losses),
        winRate=round(len(wins) / len(rows) * 100, 2) if rows else 0.0,
        netPnl=round(sum(_pnl(r) for r in rows), 4),
        totalFees=round(sum(float(r.get("fees") or 0) for r in rows), 4),
        avgProfit=round(gross_win / len(wins), 4) if wins else 0.0,
        avgLoss=round(gross_loss / len(losses), 4) if losses else 0.0,
        profitFactor=round(gross_win / gross_loss, 4) if gross_loss else (round(gross_win, 4) if gross_win else 0.0),
        maxDrawdown=round(dd, 4), todayPnl=round(daily.get(today, 0.0), 4),
        weekPnl=round(sum(_pnl(r) for r in rows if (_closed_dt(r) or week_ago) > week_ago), 4),
        spot=summarize([r for r in rows if r.get("product") == "spot"]),
        futures=summarize([r for r in rows if r.get("product") != "spot"]),
        daily=[{"date": k, "pnl": round(v, 4)} for k, v in sorted(daily.items())][-30:],
        weekly=[{"week": k, "pnl": round(v, 4)} for k, v in sorted(weekly.items())][-12:],
        curve=curve[-300:])
