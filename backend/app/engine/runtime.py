"""Process-wide engine runtime holder.

API routes access the running TradingEngine through this singleton
without depending on FastAPI DI lifecycles.
"""
from typing import Optional


class EngineRuntime:
    def __init__(self) -> None:
        self._engine = None

    def attach(self, engine) -> None:
        self._engine = engine

    @property
    def engine(self):
        if self._engine is None:
            raise RuntimeError("Trading engine is not initialized yet")
        return self._engine


engine_runtime = EngineRuntime()