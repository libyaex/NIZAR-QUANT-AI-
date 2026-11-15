"""Unified exchange adapters built on CCXT.

* ``PublicMarket``    - key-less market data (markets, tickers, candles, books).
* ``ExchangeAdapter`` - signed account/trading access (live mode).
* ``PaperAdapter``    - simulated fills against REAL prices (paper mode).

All three expose the same surface used by the execution engine, so the engine
never needs to know which one it is talking to. Capabilities (precision, limits,
contract size) are always read from the exchange's own market metadata.
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt_async

from app.models import ExchangeID, ProductType

logger = logging.getLogger(__name__)

# Market types to load per exchange. Loading everything (spot + inverse +
# options) is slow and some of those hosts are geo-blocked.
FUTURES_TYPES: Dict[str, List[str]] = {
    "binance": ["linear"],
    "bybit": ["linear"],
    "okx": ["swap"],
    "bitget": ["swap"],
    "mexc": ["swap"],
}
DEFAULT_TYPE: Dict[str, str] = {
    "binance": "future", "bybit": "swap", "okx": "swap", "bitget": "swap", "mexc": "swap",
}


def _restrict_market_types(client: Any, types: List[str]) -> None:
    """Restrict ccxt ``fetchMarkets`` to the given types (ccxt changed this
    option between a list and a dict across versions, so handle both)."""
    current = client.options.get("fetchMarkets")
    if isinstance(current, dict):
        current["types"] = types
    elif current is not None:
        client.options["fetchMarkets"] = types


def build_client(exchange: str, product: ProductType, api_key: str = "", secret: str = "",
                 password: Optional[str] = None, testnet: bool = False) -> Any:
    cls = getattr(ccxt_async, exchange)
    options: Dict[str, Any] = {"defaultType": DEFAULT_TYPE.get(exchange, "swap")}
    if exchange in ("bybit", "okx", "bitget"):
        options["defaultSubType"] = "linear"
    if product == ProductType.spot:
        options["defaultType"] = "spot"
    cfg: Dict[str, Any] = {"enableRateLimit": True, "timeout": 15000, "options": options}
    if api_key:
        cfg.update({"apiKey": api_key, "secret": secret})
        if password:
            cfg["password"] = password
    client = cls(cfg)
    _restrict_market_types(client, ["spot"] if product == ProductType.spot else FUTURES_TYPES.get(exchange, ["swap"]))
    if testnet:
        try:
            client.set_sandbox_mode(True)
        except Exception as exc:  # not every exchange has a sandbox
            logger.warning("%s sandbox not available: %s", exchange, exc)
    return client


def _is_tradable(m: Dict[str, Any], product: ProductType) -> bool:
    if m.get("active") is False:
        return False
    if product == ProductType.spot:
        return bool(m.get("spot")) and m.get("quote") == "USDT"
    return bool(m.get("swap")) and bool(m.get("linear")) and m.get("settle") == "USDT"


class PublicMarket:
    """Key-less market data access for one exchange."""

    is_paper = False

    def __init__(self, exchange: ExchangeID, product: ProductType = ProductType.futures,
                 client: Any = None):
        self.exchange_id = exchange
        self.product = product
        self.client = client or build_client(exchange.value, product)
        self._universe: List[str] = []
        self._universe_ts = 0.0

    @property
    def name(self) -> str:
        return self.exchange_id.value

    async def universe(self, max_age: float = 600) -> List[str]:
        """Dynamically discovered tradable symbols (cached)."""
        if self._universe and time.time() - self._universe_ts < max_age:
            return self._universe
        markets = await self.client.load_markets(reload=bool(self._universe))
        self._universe = [s for s, m in markets.items() if _is_tradable(m, self.product)]
        self._universe_ts = time.time()
        return self._universe

    def market(self, symbol: str) -> Optional[Dict[str, Any]]:
        return (self.client.markets or {}).get(symbol)

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """Round DOWN to the exchange's lot size (handles decimals- and tick-based precision)."""
        return float(self.client.amount_to_precision(symbol, amount))

    async def fetch_tickers(self) -> Dict[str, Any]:
        return await self.client.fetch_tickers()

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 200) -> List[list]:
        return await self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, List[List[float]]]:
        ob = await self.client.fetch_order_book(symbol, limit=limit)
        return {"bids": ob.get("bids", []), "asks": ob.get("asks", [])}

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return await self.client.fetch_ticker(symbol)

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


class ExchangeAdapter(PublicMarket):
    """Signed adapter used for LIVE trading."""

    def __init__(self, exchange: ExchangeID, product: ProductType, apiKey: str = "",
                 secret: str = "", password: Optional[str] = None, testnet: bool = False):
        super().__init__(exchange, product,
                         client=build_client(exchange.value, product, apiKey, secret, password, testnet))
        self.testnet = testnet
        self._prepared: Dict[str, int] = {}

    async def fetch_balance(self) -> Dict[str, Any]:
        bal = await self.client.fetch_balance()
        total = bal.get("total", {}) or {}
        equity = float(total.get("USDT", 0) or 0)
        free = float((bal.get("free", {}) or {}).get("USDT", 0) or 0)
        return {"equity": equity, "free": free, "raw": total}

    async def prepare_symbol(self, symbol: str, leverage: int) -> None:
        """Best-effort: isolated margin, one-way position mode, leverage.
        Each step is optional because exchanges differ in what they support."""
        if self._prepared.get(symbol) == leverage:
            return
        if self.product == ProductType.futures:
            for call, args in (
                ("set_position_mode", (False, symbol)),
                ("set_margin_mode", ("isolated", symbol)),
            ):
                fn = getattr(self.client, call, None)
                if fn is None:
                    continue
                try:
                    await fn(*args)
                except Exception as exc:  # "no change needed" is reported as an error by many exchanges
                    logger.debug("%s %s %s: %s", self.name, call, symbol, exc)
            try:
                await self.client.set_leverage(leverage, symbol)
            except Exception as exc:
                logger.debug("%s set_leverage %s: %s", self.name, symbol, exc)
        self._prepared[symbol] = leverage

    async def create_market_order(self, symbol: str, side: str, amount: float,
                                  params: Optional[Dict] = None) -> Dict[str, Any]:
        return await self.client.create_order(symbol, "market", side, amount, None, params or {})

    async def confirm_order(self, order: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        """Never assume a fill: poll the exchange until the order reports a
        terminal state (some exchanges return an empty acknowledgement)."""
        oid = order.get("id")
        latest = order
        for delay in (0.0, 0.4, 0.8, 1.5):
            if delay:
                await asyncio.sleep(delay)
            if latest.get("status") in ("closed", "canceled", "rejected", "expired") and latest.get("filled") is not None:
                return latest
            if not oid:
                break
            try:
                latest = await self.client.fetch_order(oid, symbol)
            except Exception as exc:
                logger.debug("fetch_order %s: %s", oid, exc)
                try:
                    latest = await self.client.fetch_closed_order(oid, symbol)
                except Exception:
                    continue
        return latest

    async def place_protection(self, symbol: str, side: str, qty: float,
                               stop_loss: float, take_profit: float) -> List[str]:
        """Exchange-side reduce-only SL/TP so positions stay protected even if
        this service is offline. Best-effort: returns ids that were accepted."""
        close_side = "sell" if side == "long" else "buy"
        ids: List[str] = []
        for key, price in (("stopLossPrice", stop_loss), ("takeProfitPrice", take_profit)):
            try:
                o = await self.client.create_order(
                    symbol, "market", close_side, qty, None, {key: price, "reduceOnly": True})
                if o.get("id"):
                    ids.append(str(o["id"]))
            except Exception as exc:
                logger.warning("%s protective %s not placed for %s: %s", self.name, key, symbol, exc)
        return ids

    async def cancel_orders(self, symbol: str, ids: List[str]) -> None:
        for oid in ids:
            try:
                await self.client.cancel_order(oid, symbol)
            except Exception as exc:
                logger.debug("cancel %s: %s", oid, exc)

    async def fetch_open_positions(self) -> List[Dict[str, Any]]:
        positions = await self.client.fetch_positions()
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
        close_side = "sell" if side == "long" else "buy"
        try:
            order = await self.client.create_order(symbol, "market", close_side, amount, None, {"reduceOnly": True})
            return await self.confirm_order(order, symbol)
        except Exception as exc:
            logger.error("close_position %s %s failed: %s", self.name, symbol, exc)
            return None


# --------------------------------------------------------------------------
# Paper trading: real prices, simulated account
# --------------------------------------------------------------------------
class PaperAccount:
    """One simulated USDT account shared by every exchange in paper mode."""

    def __init__(self, balance: float):
        self.start_balance = balance
        self.cash = balance
        self.positions: Dict[tuple, Dict[str, Any]] = {}
        self.marks: Dict[tuple, float] = {}

    def reset(self, balance: float) -> None:
        self.__init__(balance)

    def equity(self) -> float:
        total = self.cash
        for key, p in self.positions.items():
            mark = self.marks.get(key, p["entry"])
            diff = (mark - p["entry"]) if p["side"] == "long" else (p["entry"] - mark)
            total += diff * p["contracts"] * p["contract_size"]
        return total


class PaperAdapter:
    """Same interface as ExchangeAdapter, but fills are simulated from live
    order-book prices (buy at ask, sell at bid) with taker fees applied."""

    is_paper = True

    def __init__(self, market: PublicMarket, account: PaperAccount, taker_fee_pct: float = 0.05):
        self.market_data = market
        self.account = account
        self.fee_pct = taker_fee_pct
        self.exchange_id = market.exchange_id
        self.product = market.product
        self.client = market.client

    @property
    def name(self) -> str:
        return self.exchange_id.value

    def market(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.market_data.market(symbol)

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        return self.market_data.amount_to_precision(symbol, amount)

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        t = await self.market_data.fetch_ticker(symbol)
        last = t.get("last") or t.get("close")
        if last:
            self.account.marks[(self.name, symbol)] = float(last)
        return t

    async def fetch_balance(self) -> Dict[str, Any]:
        eq = self.account.equity()
        return {"equity": eq, "free": self.account.cash, "raw": {"USDT": eq}}

    async def prepare_symbol(self, symbol: str, leverage: int) -> None:
        return None

    async def _fill_price(self, symbol: str, side: str) -> float:
        try:
            ob = await self.market_data.fetch_order_book(symbol, limit=5)
            book = ob["asks"] if side == "buy" else ob["bids"]
            if book:
                return float(book[0][0])
        except Exception:
            pass
        t = await self.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close") or 0)

    async def create_market_order(self, symbol: str, side: str, amount: float,
                                  params: Optional[Dict] = None) -> Dict[str, Any]:
        price = await self._fill_price(symbol, side)
        if price <= 0:
            raise RuntimeError("no price available for paper fill")
        mkt = self.market(symbol) or {}
        csize = float(mkt.get("contractSize") or 1)
        fee = price * amount * csize * self.fee_pct / 100
        self.account.cash -= fee
        key = (self.name, symbol)
        self.account.marks[key] = price
        self.account.positions[key] = {
            "side": "long" if side == "buy" else "short", "contracts": amount,
            "entry": price, "contract_size": csize,
        }
        return {"id": f"paper-{uuid.uuid4().hex[:12]}", "status": "closed", "filled": amount,
                "amount": amount, "average": price, "price": price, "fee": fee}

    async def confirm_order(self, order: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        return order

    async def place_protection(self, *args: Any, **kwargs: Any) -> List[str]:
        return []

    async def cancel_orders(self, symbol: str, ids: List[str]) -> None:
        return None

    async def fetch_open_positions(self) -> List[Dict[str, Any]]:
        out = []
        for (ex, symbol), p in self.account.positions.items():
            if ex != self.name:
                continue
            out.append({"symbol": symbol, "side": p["side"], "contracts": p["contracts"],
                        "entry": p["entry"], "mark": self.account.marks.get((ex, symbol), p["entry"]),
                        "unrealizedPnl": 0.0, "leverage": 1})
        return out

    async def close_position(self, symbol: str, side: str, amount: float) -> Optional[Dict[str, Any]]:
        key = (self.name, symbol)
        pos = self.account.positions.get(key)
        close_side = "sell" if side == "long" else "buy"
        price = await self._fill_price(symbol, close_side)
        if price <= 0:
            return None
        if pos is not None:
            csize = pos["contract_size"]
            diff = (price - pos["entry"]) if pos["side"] == "long" else (pos["entry"] - price)
            qty = min(amount, pos["contracts"])
            fee = price * qty * csize * self.fee_pct / 100
            self.account.cash += diff * qty * csize - fee
            pos["contracts"] -= qty
            if pos["contracts"] <= 1e-12:
                self.account.positions.pop(key, None)
        return {"id": f"paper-{uuid.uuid4().hex[:12]}", "status": "closed", "filled": amount,
                "average": price, "price": price}

    async def close(self) -> None:
        return None


def symbol_precision(market: Dict[str, Any]) -> Dict[str, Any]:
    """Extract precision/limits info from a ccxt market dict."""
    return {
        "min_amount": market.get("limits", {}).get("amount", {}).get("min"),
        "min_cost": market.get("limits", {}).get("cost", {}).get("min"),
        "amount_precision": market.get("precision", {}).get("amount"),
        "price_precision": market.get("precision", {}).get("price"),
        "contract_size": market.get("contractSize"),
    }
