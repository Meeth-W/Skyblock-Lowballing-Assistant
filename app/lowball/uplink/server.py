"""The WebSocket server the mod connects to.

Bound to loopback only.  Nothing on the network can reach it, and nothing it
does reaches the game: the handler reads frames and never writes one.  The
library answers protocol-level pings, which is a transport concern and not a
message this app chose to send.

Runs on its own asyncio loop in a background thread; results reach the GUI
through callbacks that the Qt layer marshals onto its own thread.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from ..timeutil import now_iso
from .protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_MESSAGE_BYTES,
    Message,
    ProtocolError,
    decode,
)

log = logging.getLogger(__name__)

Handler = Callable[[Message], Awaitable[None] | None]


@dataclass
class UplinkStatus:
    connected: bool = False
    mod_version: str | None = None
    mc_version: str | None = None
    player_name: str | None = None
    last_message_ts: str | None = None
    messages: int = 0
    errors: int = 0

    @property
    def label(self) -> str:
        if not self.connected:
            return "Mod not connected"
        who = self.player_name or "unknown player"
        return f"Connected: {who} on {self.mc_version or '?'}"


class UplinkServer:
    """Listens for the mod.  Read-only by construction."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        on_message: Handler | None = None,
        on_status: Callable[[UplinkStatus], None] | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            # The mod runs on the same machine.  Binding anywhere else would
            # expose a trade feed to the network for no benefit.
            raise ValueError("the uplink binds to loopback only")
        self.host = host
        self.port = port
        self.on_message = on_message
        self.on_status = on_status
        self.status = UplinkStatus()
        self._server: Any = None
        self._stop = asyncio.Event()

    async def _handle(self, connection: ServerConnection) -> None:
        self.status.connected = True
        self._announce()
        log.info("mod connected from %s", connection.remote_address)
        try:
            async for frame in connection:
                await self._dispatch(frame)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.status.connected = False
            self.status.player_name = None
            self._announce()
            log.info("mod disconnected")

    async def _dispatch(self, frame: str | bytes) -> None:
        try:
            message = decode(frame)
        except ProtocolError as exc:
            self.status.errors += 1
            log.warning("dropped a malformed frame: %s", exc)
            return
        if message is None:
            # A newer mod may send types this build does not know.  Ignoring
            # them is the whole point of having a version-tolerant protocol.
            return

        self.status.messages += 1
        self.status.last_message_ts = now_iso()
        from .protocol import Hello

        if isinstance(message, Hello):
            self.status.mod_version = message.mod_version
            self.status.mc_version = message.mc_version
            self.status.player_name = message.player_name
            self._announce()

        if self.on_message is None:
            return
        try:
            result = self.on_message(message)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 - one bad handler must not drop the feed
            self.status.errors += 1
            log.exception("uplink handler failed on %s", type(message).__name__)

    def _announce(self) -> None:
        if self.on_status is not None:
            try:
                self.on_status(self.status)
            except Exception:  # noqa: BLE001
                log.exception("uplink status callback failed")

    async def serve_forever(self) -> None:
        self._stop.clear()
        async with serve(
            self._handle,
            self.host,
            self.port,
            max_size=MAX_MESSAGE_BYTES,
            ping_interval=20,
            ping_timeout=20,
        ) as server:
            self._server = server
            log.info("uplink listening on ws://%s:%d", self.host, self.port)
            await self._stop.wait()
        self._server = None

    def stop(self) -> None:
        self._stop.set()
