"""Main API routes: engine, exchanges, scanner, positions, missions, performance."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import AuthUser, current_user
from app.engine.runtime import engine_runtime
from app.models import (
    EngineStatusOut,
    ExchangeConfigIn,
    ExchangeStatus,
    MissionIn,
    MissionUpdate,
    PerformanceOut,
    PositionSnapshot,
    RiskSettings,
    ScannerConfig,
    StartStopIn,
    TradingState,
)
from app.services.supabase_client import get_supabase
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _mission_to_api(row: Dict) -> Dict:
    starting = float(row.get("starting_capital", 0))
    target = float(row.get("target_capital", 0))
    realized = float(row.get("realized_profit", 0))
    unrealized = float(row.get("unrealized_profit", 0))
    current = starting + realized
    span = target - starting
    progress = 0.0 if span <= 0 else min(100.0, max(0.0, (current - starting) / span * 100))
    status = row.get("status", "active")
    return {
        "id": row.get("id"),
        "startingCapital": starting,
        "currentCapital": round(current, 4),
        "targetCapital": target,
        "realizedProfit": round(realized, 4),
        "unrealizedProfit": round(unrealized, 4),
        "remaining": round(max(0.0, target - current), 4),
        "progressPct": round(progress, 2),
        "status": status,
        "compounding": bool(row.get("compounding", True)),
        "startedAt": row.get("started_at") or row.get("created_at"),
        "completedAt": row.get("completed_at"),
        "allowsNewTrades": status == "active" and current < target,
    }


def _settings_upsert(db, user_id: str, risk: Optional[dict] = None, scanner: Optional[dict] = None) -> None:
    """Save settings so the engine restores them after a backend restart."""
    try:
        row = {
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if risk is not None:
            row["risk_settings"] = risk
        if scanner is not None:
            row["scanner_settings"] = scanner
        db.table("user_settings").upsert(row).execute()
    except Exception as exc:
        logger.warning("settings persist failed: %s", exc)


@router.get("/health")
async def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/status", response_model=EngineStatusOut)
async def status(user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    if engine.adapters:
        await engine.refresh_equity()
    return engine.status()


@router.post("/trading/ctl", response_model=EngineStatusOut)
async def trading_control(body: StartStopIn, user: AuthUser = Depends(current_user)):
    action = body.action
    if action not in ("start", "stop", "halt"):
        raise HTTPException(400, "action must be start|stop|halt")
    engine = engine_runtime.engine
    await engine.load_user_exchanges(user.id)
    await engine.set_trading(user.id, action)
    if engine.adapters:
        await engine.refresh_equity()
    return engine.status()


@router.post("/trading/close-all")
async def close_all(user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    closed = await engine.close_all_positions()
    return {"closed": closed}


@router.get("/exchanges", response_model=List[ExchangeStatus])
async def list_exchanges(user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    db = get_supabase(get_settings())
    resp = db.table("exchange_configs").select("*").eq("user_id", user.id).execute()
    rows = resp.data or []
    out = []
    for row in rows:
        adapter = engine.adapters.get(row["id"])
        connected = adapter is not None
        markets = 0
        if connected:
            try:
                markets = len(adapter.client.markets) if adapter.client.markets else 0
            except Exception:
                markets = 0
        out.append(ExchangeStatus(
            id=row["id"],
            exchange=row["exchange"],
            label=row.get("label", "default"),
            product=row.get("product", "futures"),
            testnet=bool(row.get("testnet", False)),
            connected=connected,
            markets=markets,
            createdAt=row.get("created_at"),
        ))
    return out


@router.post("/exchanges", response_model=ExchangeStatus)
async def connect_exchange(body: ExchangeConfigIn, user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    engine._ensure_vault()
    vault = engine._vault
    db = get_supabase(get_settings())
    row = {
        "user_id": user.id,
        "exchange": body.exchange.value,
        "label": body.label,
        "product": body.product.value,
        "testnet": body.testnet,
        "api_key_enc": vault.encrypt(body.apiKey),
        "secret_enc": vault.encrypt(body.secret),
        "password_enc": vault.encrypt(body.password) if body.password else None,
    }
    resp = db.table("exchange_configs").insert(row).execute()
    created = (resp.data or [])[0]
    await engine.load_user_exchanges(user.id)
    adapter = engine.adapters.get(created["id"])
    return ExchangeStatus(
        id=created["id"],
        exchange=created["exchange"],
        label=created["label"],
        product=created["product"],
        testnet=bool(created.get("testnet", False)),
        connected=adapter is not None,
        createdAt=created.get("created_at"),
    )


@router.delete("/exchanges/{cfg_id}")
async def disconnect_exchange(cfg_id: str, user: AuthUser = Depends(current_user)):
    db = get_supabase(get_settings())
    resp = db.table("exchange_configs").select("id").eq("id", cfg_id).eq("user_id", user.id).execute()
    if not (resp.data or []):
        raise HTTPException(404, "Exchange config not found")
    db.table("exchange_configs").delete().eq("id", cfg_id).execute()
    engine = engine_runtime.engine
    engine.adapters.pop(cfg_id, None)
    engine.scanners.pop(cfg_id, None)
    engine.executors.pop(cfg_id, None)
    return {"removed": True}


@router.get("/scanner")
async def scanner(limit: int = 20, user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    opps = [o.model_dump(mode="json") for o in engine.opportunities[:limit]]
    return {"opportunities": opps, "scanCount": len(engine.opportunities)}


@router.get("/scanner/raw")
async def scanner_raw(user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    out = []
    for scanner in engine.scanners.values():
        out.extend(scanner.results[:10])
    return {"results": out[:40]}


@router.get("/positions", response_model=List[PositionSnapshot])
async def positions(user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    out: List[PositionSnapshot] = []
    for ex in engine.executors.values():
        out.extend(ex.snapshots())
    return out


@router.get("/settings/risk", response_model=RiskSettings)
async def get_risk(user: AuthUser = Depends(current_user)):
    return engine_runtime.engine.risk.settings


@router.put("/settings/risk", response_model=RiskSettings)
async def put_risk(body: RiskSettings, user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    engine.risk.settings_update(body)
    db = get_supabase(get_settings())
    _settings_upsert(db, user.id, risk=body.model_dump())
    return body


@router.get("/settings/scanner", response_model=ScannerConfig)
async def get_scanner_cfg(user: AuthUser = Depends(current_user)):
    return engine_runtime.engine.scanner_config


@router.put("/settings/scanner", response_model=ScannerConfig)
async def put_scanner_cfg(body: ScannerConfig, user: AuthUser = Depends(current_user)):
    engine = engine_runtime.engine
    engine.scanner_config = body
    for scanner in engine.scanners.values():
        scanner.config = body.model_dump()
    db = get_supabase(get_settings())
    _settings_upsert(db, user.id, scanner=body.model_dump())
    return body


@router.get("/missions")
async def list_missions(user: AuthUser = Depends(current_user)):
    db = get_supabase(get_settings())
    resp = db.table("profit_missions").select("*").eq("user_id", user.id).order("created_at", desc=True).execute()
    rows = resp.data or []
    return {"missions": [_mission_to_api(r) for r in rows]}


@router.post("/missions")
async def create_mission(body: MissionIn, user: AuthUser = Depends(current_user)):
    if body.targetCapital <= body.startingCapital:
        raise HTTPException(400, "Target must exceed starting capital")
    db = get_supabase(get_settings())
    row = {
        "user_id": user.id,
        "starting_capital": body.startingCapital,
        "target_capital": body.targetCapital,
        "realized_profit": 0.0,
        "unrealized_profit": 0.0,
        "status": "active",
        "compounding": body.compounding,
    }
    resp = db.table("profit_missions").insert(row).execute()
    created = (resp.data or [])[0]
    return _mission_to_api(created)


@router.put("/missions/{mission_id}")
async def update_mission(mission_id: str, body: MissionUpdate, user: AuthUser = Depends(current_user)):
    db = get_supabase(get_settings())
    updates = {}
    if body.status is not None:
        if body.status not in ("active", "paused", "completed"):
            raise HTTPException(400, "invalid status")
        updates["status"] = body.status
    if body.compounding is not None:
        updates["compounding"] = body.compounding
    if not updates:
        raise HTTPException(400, "nothing to update")
    db.table("profit_missions").update(updates).eq("id", mission_id).eq("user_id", user.id).execute()
    resp = db.table("profit_missions").select("*").eq("id", mission_id).execute()
    row = (resp.data or [])[0]
    return _mission_to_api(row)


@router.get("/performance", response_model=PerformanceOut)
async def performance(user: AuthUser = Depends(current_user)):
    db = get_supabase(get_settings())
    resp = db.table("trades").select("*").eq("user_id", user.id).order("created_at", desc=False).execute()
    rows = [r for r in (resp.data or []) if r.get("status") == "closed"]
    return compute_performance(rows)


@router.get("/trades")
async def trades(limit: int = 100, user: AuthUser = Depends(current_user)):
    db = get_supabase(get_settings())
    resp = db.table("trades").select("*").eq("user_id", user.id).order("created_at", desc=True).limit(limit).execute()
    return {"trades": resp.data or []}


def compute_performance(rows: List[dict]) -> PerformanceOut:
    import numpy as np
    total = len(rows)
    wins = [r for r in rows if float(r.get("realized_pnl") or 0) > 0]
    losses = [r for r in rows if float(r.get("realized_pnl" or 0) or 0) <= 0]
    net = sum(float(r.get("realized_pnl") or 0) for r in rows)
    fees = sum(float(r.get("fees") or 0) for r in rows)
    gross_win = sum(float(r.get("realized_pnl") or 0) for r in wins)
    gross_loss = abs(sum(float(r.get("realized_pnl") or 0) for r in losses))
    curve = np.cumsum([float(r.get("realized_pnl") or 0) for r in rows]) if rows else np.array([0.0])
    peak = np.maximum.accumulate(curve) if len(curve) else np.array([0.0])
    dd = float((peak - curve).max()) if len(curve) else 0.0
    now = datetime.now(timezone.utc)
    today_rows = [r for r in rows if r.get("closed_at") and str(r["closed_at"])[:10] == now.strftime("%Y-%m-%d")]
    week_rows = []
    for r in rows:
        if not r.get("closed_at"):
            continue
        try:
            closed = datetime.fromisoformat(str(r["closed_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - closed <= timedelta(days=7):
            week_rows.append(r)
    spot_rows = [r for r in rows if r.get("product") == "spot"]
    fut_rows = [r for r in rows if r.get("product") == "futures"]

    def summarize(sub):
        if not sub:
            return {"trades": 0, "netPnl": 0.0, "winRate": 0.0}
        w = sum(1 for r in sub if float(r.get("realized_pnl") or 0) > 0)
        return {
            "trades": len(sub),
            "netPnl": round(sum(float(r.get("realized_pnl") or 0) for r in sub), 4),
            "winRate": round(w / len(sub) * 100, 2),
        }

    return PerformanceOut(
        totalTrades=total,
        wins=len(wins),
        losses=len(losses),
        winRate=round(len(wins) / total * 100, 2) if total else 0.0,
        netPnl=round(net, 4),
        totalFees=round(fees, 4),
        avgProfit=round(gross_win / len(wins), 4) if wins else 0.0,
        avgLoss=round(gross_loss / len(losses), 4) if losses else 0.0,
        profitFactor=round(gross_win / gross_loss, 4) if gross_loss else 0.0,
        maxDrawdown=round(dd, 4),
        todayPnl=round(sum(float(r.get("realized_pnl") or 0) for r in today_rows), 4),
        weekPnl=round(sum(float(r.get("realized_pnl") or 0) for r in week_rows), 4),
        spot=summarize(spot_rows),
        futures=summarize(fut_rows),
    )
