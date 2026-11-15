"""FastAPI entry point. The trading engine starts with the process and keeps
running regardless of whether any frontend is connected."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.engine.engine import TradingEngine
from app.engine.runtime import engine_runtime
from app.services.supabase_client import get_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nizar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = TradingEngine(db=get_supabase(settings), settings=settings)
    engine_runtime.attach(engine)
    await engine.start()
    logger.info("Engine started: exchanges=%s mode=%s state=%s",
                settings.market_exchanges, engine.mode.value, engine.state.value)
    try:
        yield
    finally:
        await engine.stop()


app = FastAPI(title="NIZAR QUANT AI", version="2.0.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/")
async def root():
    return {"name": "NIZAR QUANT AI", "docs": "/docs", "health": "/api/health"}
