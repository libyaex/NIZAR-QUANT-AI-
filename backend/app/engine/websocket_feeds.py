"""Native exchange WebSocket market data (public channels, no API keys).

One connection per exchange. Each trade tick is forwarded as
``on_tick(exchange, market_id, price, ts_ms)``; the engine uses ticks to keep the
live 1m/2m/... candles current between REST refreshes. If a feed is blocked or
drops, REST polling in the market hub keeps data flowing.
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp

logger = logging.getLogger(__name__)

Tick = Tuple[str, float, int]  # (market_id, price, ts_ms)

WS_URL: Dict[str, str] = {
    "bybit": "wss://stream.bybit.com/v5/public/linear",
    "okx": "wss://ws.okx.com:8443/ws/v5/public",
    "bitget": "wss://ws.bitget.com/v2/ws/public",
    "mexc": "wss://contract.mexc.com/edge",
}
PING: Dict[str, Any] = {
    "bybit": json.dumps({"op": "ping"}),
    "okx": "ping",
    "bitget": "ping",
    "mexc": json.dumps({"method": "ping"}),
}


def _binance_url(ids: List[str]) -> str:
    streams = "/".join(f"{i.lower()}@trade" for i in ids[:100])
    return f"wss://fstream.binance.com/stream?streams={streams}"


async def _subscribe(exchange: str, ws: aiohttp.ClientWebSocketResponse, ids: List[str]) -> None:
    if exchange == "binance":
        return  # streams are part of the URL
    for i in ids:
        if exchange == "bybit":
            msg: Dict[str, Any] = {"op": "subscribe", "args": [f"publicTrade.{i}"]}
        elif exchange == "okx":
            msg = {"op": "subscribe", "args": [{"channel": "trades", "instId": i}]}
        elif exchange == "bitget":
            msg = {"op": "subscribe", "args": [{"instType": "USDT-FUTURES", "channel": "trade", "instId": i}]}
        elif exchange == "mexc":
            msg = {"method": "sub.deal", "param": {"symbol": i}}
        else:
            return
        await ws.send_json(msg)
        await asyncio.sleep(0.02)  # stay well inside per-second subscribe limits


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse(exchange: str, msg: Any) -> List[Tick]:
    out: List[Tick] = []
    if not isinstance(msg, dict):
        return out
    now = int(time.time() * 1000)
    if exchange == "binance":
        d = msg.get("data") or {}
        if d.get("s") and _f(d.get("p")) > 0:
            out.append((d["s"], _f(d["p"]), int(d.get("T") or now)))
    elif exchange == "bybit":
        if str(msg.get("topic", "")).startswith("publicTrade"):
            for d in msg.get("data") or []:
                if d.get("s") and _f(d.get("p")) > 0:
                    out.append((d["s"], _f(d["p"]), int(d.get("T") or now)))
    elif exchange == "okx":
        if (msg.get("arg") or {}).get("channel") == "trades":
            for d in msg.get("data") or []:
                if d.get("instId") and _f(d.get("px")) > 0:
                    out.append((d["instId"], _f(d["px"]), int(d.get("ts") or now)))
    elif exchange == "bitget":
        inst = (msg.get("arg") or {}).get("instId")
        if inst and msg.get("data") and (msg.get("arg") or {}).get("channel") == "trade":
            for d in msg["data"]:
                if _f(d.get("price")) > 0:
                    out.append((inst, _f(d["price"]), int(d.get("ts") or now)))
    elif exchange == "mexc":
        if msg.get("channel") == "push.deal" and msg.get("symbol"):
            data = msg.get("data")
            for d in (data if isinstance(data, list) else [data] if data else []):
                if _f(d.get("p")) > 0:
                    out.append((msg["symbol"], _f(d["p"]), int(d.get("t") or now)))
    return out


class ExchangeWebSocketFeed:
    def __init__(self, exchange: str, on_tick: Callable[[str, str, float, int], None]):
        self.exchange = exchange
        self.on_tick = on_tick
        self.ids: Set[str] = set()
        self.connected = False
        self.ticks = 0
        self.last_tick = 0.0
        self.last_error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._changed = asyncio.Event()

    def set_symbols(self, ids: List[str]) -> None:
        new = set(ids)
        if new != self.ids:
            self.ids = new
            self._changed.set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _pinger(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        payload = PING.get(self.exchange)
        if payload is None:
            return
        while True:
            await asyncio.sleep(15)
            await ws.send_str(payload)

    async def _run(self) -> None:
        backoff = 1.0
        while self._running:
            if not self.ids:
                await asyncio.sleep(2)
                continue
            ids = sorted(self.ids)
            self._changed.clear()
            url = _binance_url(ids) if self.exchange == "binance" else WS_URL.get(self.exchange)
            if url is None:
                return
            ping_task: Optional[asyncio.Task] = None
            try:
                timeout = aiohttp.ClientTimeout(total=None, connect=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(url, heartbeat=20) as ws:
                        self.connected, self.last_error, backoff = True, None, 1.0
                        await _subscribe(self.exchange, ws, ids)
                        ping_task = asyncio.create_task(self._pinger(ws))
                        while self._running and not self._changed.is_set():
                            try:
                                raw = await asyncio.wait_for(ws.receive(), timeout=5)
                            except asyncio.TimeoutError:
                                continue
                            if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                                            aiohttp.WSMsgType.ERROR):
                                break
                            if raw.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                msg = json.loads(raw.data)
                            except ValueError:
                                continue
                            for mid, price, ts in parse(self.exchange, msg):
                                self.ticks += 1
                                self.last_tick = time.time()
                                try:
                                    self.on_tick(self.exchange, mid, price, ts)
                                except Exception:
                                    logger.debug("tick handler error", exc_info=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:200]
                logger.warning("WS %s disconnected (%s); retry in %.0fs", self.exchange, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                self.connected = False
                if ping_task:
                    ping_task.cancel()
