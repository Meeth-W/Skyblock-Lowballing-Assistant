"""The bridge between the asyncio side and the Qt side.

Network work -- the uplink server, every Coflnet request, a bazaar refresh
-- runs on one asyncio loop on a background thread.  Results come back as Qt
signals, which Qt delivers on the GUI thread.

The GUI thread never waits on network I/O.  A customer is standing there; a
window that stops repainting because a request is slow is worse than a window
showing a stale number.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class AsyncBridge(QObject):
    """Owns the asyncio loop and the thread it runs on."""

    started = Signal()
    stopped = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def is_running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    def start(self, timeout: float = 5.0) -> None:
        if self._thread is not None:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="lowball-async", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("the async loop did not start")
        self.started.emit()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.call_soon(self._ready.set)
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                loop.close()
                self._loop = None

    def stop(self, timeout: float = 5.0) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout)
        self._thread = None
        self.stopped.emit()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        """Run a coroutine on the loop.  Safe to call from the GUI thread."""
        loop = self._loop
        if loop is None:
            raise RuntimeError("the async loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def run_later(self, fn: Callable[[], Any]) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(fn)


def report_failure(future: Future, what: str) -> None:
    """Attach a callback that logs rather than losing an exception silently."""

    def _done(done: Future) -> None:
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            log.exception("%s failed", what, exc_info=error)

    future.add_done_callback(_done)
