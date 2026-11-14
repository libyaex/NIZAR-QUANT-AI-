"""Native exchange WebSocket market data feeds.

The prompt requires official exchange WebSocket streams for real-time data.
Each feed opens public (key-less) trade channels for the scanned symbols and
forwards ticks to the engine's candle aggregator, so indicators update from
live data instead of REST polling alone.
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set

import aiohttp

logger = logging.getLogger(__name__)

# Public WS endpoints (no API key required for market data)
WS_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "binance": {"url": "wss://fstream.binance.com/stream", "style": "combined"},
    "bybit": {"url": "wss://stream.bybit.com/v5/public/linear", "style": "bybit"},
    "okx": {"url": "wss://ws.okx.com:8443/ws/v5/public", "style": "okx"},
    "bitget": {"url": "wss://ws.bitget.com/v2/ws/public", "style": "bitget"},
    "mexc": {"url": "wss://contract.mexc.com/edge", "style": "mexc"},
}


async def _bybit_subscribe(ws: aiohttp.ClientWebSocketResponse, symbols: List[str]) -> None:
    for sym in symbols:
        raw = sym.split(":")[0].replace("/", "")
        await ws.send_json({"op": "subscribe", "args": [f"publicTrade.{raw}"]})


async def _okx_subscribe(ws: aiohttp.ClientWebSocketResponse, symbols: List[str]) -> None:
    for sym in symbols:
        base_quote = sym.split(":")[0].replace("/", "-")
        inst_id = f"{base_quote}-SWAP" if "-USDT" in base_quote else base_quote
        await ws.send_json({"op": "subscribe", "args": [{"channel": "trades", "instId": inst_id}]})


async def _bitget_subscribe(ws: aiohttp.ClientWebSocketResponse, symbols: List[str]) -> None:
    for sym in symbols:
        raw = sym.split(":")[0].replace("/", "")
        await ws.send_json({"op": "subscribe", "args": [{"instType": "mc", "channel": "trade", "instId": raw}]})


async def _mexc_subscribe(ws: aiohttp.ClientWebSocketResponse, symbols: List[str]) -> None:
    for sym in symbols:
        raw = sym.split(":")[0].replace("/", "")
        payload = {"method": "sub", "param": {"channel": f"sub.{raw}@trade@100ms"}}
        await ws.send_str(json.dumps(payload))


SUBSCRIBERS = {
    "bybit": _bybit_subscribe,
    "okx": _okx_subscribe,
    "bitget": _bitget_subscribe,
    "mexc": _mexc_subscribe,
}


def _binance_url(symbols: List[str]) -> str:
    streams = "/".join(
        s.split(":")[0].replace("/", "").lower() + "@trade" for s in symbols[:100]
    )
    return f"wss://fstream.binance.com/stream?streams={streams}"


def _parse_binance(msg: Dict[str, Any]):
    data = msg.get("data") or {}
    symbol, price, size = data.get("s"), float(data.get("p") or 0), float(data.get("q") or 0)
    if symbol and price > 0:
        return symbol, price, size
    return None


def _parse_bybit(msg: Dict[str, Any]):
    topic = msg.get("topic", "")
    if topic.startswith("publicTrade") and msg.get("type") == "snapshot":
        d = msg.get("data", [{}])[0] if msg.get("data") else None
        if d:
            symbol, price, size = d.get("s"), float(d.get("p") or 0), float(d.get("v") or 0)
            if symbol and price > 0:
                return symbol, price, size
    return None


def _parse_okx(msg: Dict[str, Any]):
    if msg.get("arg", {}).get("channel") == "trades" and msg.get("data"):
        d = msg["data"][0]
        symbol, price, size = d.get("instId"), float(d.get("px") or 0), float(d.get("sz") or 0)
        if symbol and price > 0:
            return symbol, price, size
    return None


def _parse_bitget(msg: Dict[str, Any]):
    if msg.get("action") == "snapshot" and msg.get("data"):
        d = msg["data"][0]
        symbol, price, size = d.get("instId"), float(d.get("price") or 0), float(d.get("size") or 0)
        if symbol and price > 0:
            return symbol, price, size
    return None


def _parse_mexc(msg: Dict[str, Any]):
    channel = msg.get("channel", "")
    if channel.endswith("@trade@100ms") and msg.get("data"):
        d = msg["data"]
        symbol, price, size = d.get("s"), float(d.get("p") or 0), float(d.get("v") or 0)
        if symbol and price > 0:
            return symbol, price, size
    return None


PARSERS = {
    "binance": _parse_binance,
    "bybit": _parse_bybit,
    "okx": _parse_okx,
    "bitget": _parse_bitget,
    "mexc": _parse_mexc,
}


class ExchangeWebSocketFeed:
    """One native WebSocket connection per exchange for public trade data.

    No API keys flow through these sockets. Ticks are delivered via the
    on_tick callback as (exchange, raw_symbol, price, size).
    """

    def __init__(self, exchange: str, on_tick: Callable, symbols: Optional[List[str]] = None):
        self.exchange = exchange
        self.on_tick = on_tick
        self.symbols: Set[str] = set(symbols or [])
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.connected: bool = False

    def set_symbols(self, symbols: List[str]) -> None:
        """Update the subscribed symbol set (applied on reconnect)."""
        self.symbols = set(symbols)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        cfg = WS_ENDPOINTS.get(self.exchange)
        if cfg is None:
            logger.debug("no WS endpoint for %s", self.exchange)
            return
        backoff = 1.0
        while self._running:
            if not self.symbols:
                await asyncio.sleep(5)
                continue
            url = _binance_url(list(self.symbols)) if self.exchange == "binance" else cfg["url"]
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, heartbeat=20) as ws:
                        logger.info("WS connected: %s (%d symbols)", self.exchange, len(self.symbols))
                        self.connected = True
                        backoff = 1.0
                        subscriber = SUBSCRIBERS.get(self.exchange)
                        if subscriber is not None:
                            await subscriber(ws, list(self.symbols))
                        async for raw in ws:
                            if not self._running:
                                break
                            if raw.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                msg = json.loads(raw.data)
                            except (ValueError, TypeError):
                                continue
                            parsed = PARSERS.get(self.exchange)
                            if parsed is None:
                                continue
                            result = parsed(msg)
                            if result is None:
                                continue
                            symbol, price, size = result
                            try:
                                self.on_tick(self.exchange, symbol, price, size)
                            except Exception:
                                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("WS %s disconnected (%s); reconnect in %.0fs", self.exchange, exc, backoff)
                self.connected = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
