"""FastAPI application entry point with background engine lifecycle."""
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
    db = get_supabase(settings)
    engine = TradingEngine(db=db, settings=settings)
    engine_runtime.attach(engine)
    task = await engine.start()
    logger.info("Trading engine started (background market mode)")
    try:
        yield
    finally:
        await engine.stop()
        task.cancel()
        logger.info("Trading engine stopped")


app = FastAPI(title="NIZAR QUANT AI", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)