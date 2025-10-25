from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Set

from aiohttp import web, WSMsgType


class CaptionWebUI:
    """Lightweight Web UI for live captions via WebSocket.

    Serves a static page and accepts WS connections on /ws. Use broadcast()
    to push updates: {"type": "partial"|"final", "text": "..."}.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, web_root: Optional[Path] = None) -> None:
        self.host = host
        self.port = port
        self.web_root = web_root or (Path(__file__).resolve().parent.parent.parent / "web")
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._clients: Set[web.WebSocketResponse] = set()
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_static("/static", str(self.web_root / "static"))
        self._app = app
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logging.info("Caption Web UI running at http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        for ws in list(self._clients):
            await ws.close()
        self._clients.clear()
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._app = None

    async def _handle_index(self, request: web.Request) -> web.Response:
        index_path = self.web_root / "index.html"
        return web.FileResponse(path=str(index_path))

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    # Currently we don't expect inbound messages; ignore pings
                    pass
                elif msg.type == WSMsgType.ERROR:
                    logging.warning("WebSocket error: %s", ws.exception())
        finally:
            self._clients.discard(ws)
        return ws

    async def broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(payload)
        coros = [ws.send_str(data) for ws in list(self._clients) if not ws.closed]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

