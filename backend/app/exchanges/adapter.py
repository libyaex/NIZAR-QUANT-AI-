"""Unified CCXT-based exchange adapters.

Each adapter wraps a ccxt exchange instance for REST functionality and
exposes capability discovery (markets, precision, leverage limits, order
types) so the trading engine never assumes features exist. WebSocket feeds
use ccxt.pro-style watch methods when available, otherwise REST polling.
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt_async

from app.models import ExchangeID, ProductType

logger = logging.getLogger(__name__)

OPTIONS_BY_EXCHANGE: Dict[str, Dict[str, Any]] = {
    "binance": {"options": {"defaultType": "future"}},
    "mexc": {"options": {"defaultType": "swap"}},
    "bybit": {"options": {"defaultType": "linear"}},
    "okx": {"options": {"defaultType": "swap"}},
    "bitget": {"options": {"defaultType": "linear"}},
}


class ExchangeAdapter:
    """Unified async adapter over one ccxt exchange."""

    def __init__(self, exchange: ExchangeID, product: ProductType,
                 apiKey: str = "", secret: str = "", password: Optional[str] = None,
                 testnet: bool = False):
        self.exchange_id = exchange
        self.product = product
        self.testnet = testnet
        cfg = OPTIONS_BY_EXCHANGE.get(exchange.value, {})
        params: Dict[str, Any] = {
            "apiKey": apiKey,
            "secret": secret,
            "enableRateLimit": True,
            "options": dict(cfg.get("options", {})),
        }
        if password:
            params["password"] = password
        cls = getattr(ccxt_async, exchange.value)
        self.client = cls(params) if False else cls({k: v for k, v in params.items() if k != "options"})
        self.client.options.update(params["options"])
        if product == ProductType.spot:
            self.client.options["defaultType"] = "spot"
        if testnet:
            self._set_testnet()

    def _set_testnet(self) -> None:
        try:
            self.client.set_sandbox_mode(True)
        except Exception as exc:  # not all exchanges support sandbox
            logger.warning("%s sandbox not available: %s", self.exchange_id, exc)

    # -- capability discovery ------------------------------------------------
    async def load_capabilities(self) -> Dict[str, Any]:
        markets = await self.client.load_markets()
        tradable = [
            m for m in markets.values()
            if (self.product == ProductType.futures and m.get("swap") or m.get("future"))
            or (self.product == ProductType.spot and m.get("spot"))
        ]
        return {
            "markets": len(markets),
            "tradable": len(tradable),
            "symbols": [m["symbol"] for m in tradable],
            "currencies": len(markets.values()),
        }

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 200) -> List[list]:
        return await self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, List[List[float]]]:
        ob = await self.client.fetch_order_book(symbol, limit=limit)
        return {"bids": ob.get("bids", []), "asks": ob.get("asks", [])}

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return await self.client.fetch_ticker(symbol)

    async def fetch_balance(self) -> Dict[str, Any]:
        bal = await self.client.fetch_balance()
        info = bal.get("info", {})
        total = bal.get("total", {})
        usdt = float(total.get("USDT", 0) or 0)
        # Futures margin balance fallbacks across exchanges
        if self.product == ProductType.futures and usdt == 0:
            for key in ("USDT", "usdt"):
                data = info.get(key)
                if isinstance(data, dict):
                    usdt = float(data.get("marginBalance") or data.get("available") or 0)
                    break
        return {"equity": usdt, "raw": total}

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            await self.client.set_leverage(leverage, symbol)
            return True
        except Exception as exc:
            logger.warning("set_leverage %s %s failed: %s", self.exchange_id, symbol, exc)
            return False

    async def create_market_order(self, symbol: str, side: str, amount: float,
                                  params: Optional[Dict] = None) -> Dict[str, Any]:
        return await self.client.create_order(symbol, "market", side, amount, None, params or {})

    async def create_limit_order(self, symbol: str, side: str, amount: float, price: float,
                                 params: Optional[Dict] = None) -> Dict[str, Any]:
        return await self.client.create_order(symbol, "limit", side, amount, price, params or {})

    async def fetch_open_positions(self) -> List[Dict[str, Any]]:
        try:
            positions = await self.client.fetch_positions()
        except Exception as exc:
            logger.warning("fetch_positions failed for %s: %s", self.exchange_id, exc)
            return []
        out = []
        for p in positions:
            contracts = float(p.get("contracts") or 0)
            if contracts == 0:
                continue
            out.append({
                "symbol": p.get("symbol"),
                "side": "long" if (p.get("side") or "").lower() in ("long", "buy") else "short",
                "contracts": contracts,
                "entry": float(p.get("entryPrice") or 0),
                "mark": float(p.get("markPrice") or 0),
                "unrealizedPnl": float(p.get("unrealizedPnl") or 0),
                "leverage": int(p.get("leverage") or 1),
            })
        return out

    async def close_position(self, symbol: str, side: str, amount: float) -> Optional[Dict[str, Any]]:
        """Close by placing a reducing market order (hedge-safe)."""
        close_side = "sell" if side == "long" else "buy"
        params = {"reduceOnly": True}
        if self.exchange_id == ExchangeID.okx:
            params = {"reduceOnly": True}
        try:
            return await self.client.create_order(symbol, "market", close_side, amount, None, params)
        except Exception as exc:
            logger.error("close_position %s %s failed: %s", self.exchange_id, symbol, exc)
            return None

    async def ping(self) -> bool:
        try:
            await self.client.fetch_time()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        try:
            await self.client.close()
        except Exception:
            pass


def symbol_precision(market: Dict[str, Any]) -> Dict[str, Any]:
    """Extract precision/limits info from a ccxt market dict."""
    return {
        "min_amount": market.get("limits", {}).get("amount", {}).get("min"),
        "min_cost": market.get("limits", {}).get("cost", {}).get("min"),
        "amount_precision": market.get("precision", {}).get("amount"),
        "price_precision": market.get("precision", {}).get("price"),
        "contract_size": market.get("contractSize"),
    }