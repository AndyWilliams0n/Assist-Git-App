from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from app.connection_monitor.base import AbstractConnectivityBackend


class ConnectionMonitor:
    def __init__(self, backend: AbstractConnectivityBackend) -> None:
        self._backend = backend
        self._connected_event = threading.Event()
        self._connected_event.set()
        self._on_disconnect_callbacks: list[Callable] = []
        self._on_reconnect_callbacks: list[Callable] = []
        self._subscribers: set[Callable[[bool], None]] = set()

    def start(self) -> None:
        self._backend.start(on_change=self._handle_change)

    def stop(self) -> None:
        self._backend.stop()

    def is_connected(self) -> bool:
        return self._connected_event.is_set()

    def wait_until_connected(self, timeout: float | None = None) -> bool:
        return self._connected_event.wait(timeout=timeout)

    async def wait_until_connected_async(self, poll_interval: float = 1.0) -> None:
        while not self._connected_event.is_set():
            await asyncio.sleep(poll_interval)

    def on_disconnect(self, callback: Callable) -> None:
        self._on_disconnect_callbacks.append(callback)

    def on_reconnect(self, callback: Callable) -> None:
        self._on_reconnect_callbacks.append(callback)

    def subscribe(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        self._subscribers.add(callback)

        def unsubscribe() -> None:
            self._subscribers.discard(callback)

        return unsubscribe

    def _handle_change(self, is_connected: bool) -> None:
        if is_connected:
            print('[connection_monitor] Internet connection restored.')
            self._connected_event.set()
            callbacks = self._on_reconnect_callbacks
        else:
            print('[connection_monitor] Internet connection lost — agents paused.')
            self._connected_event.clear()
            callbacks = self._on_disconnect_callbacks

        for cb in callbacks:
            try:
                cb()
            except Exception as exc:
                print(f'[connection_monitor] Callback error: {exc}')

        for sub in list(self._subscribers):
            try:
                sub(is_connected)
            except Exception as exc:
                print(f'[connection_monitor] Subscriber error: {exc}')
