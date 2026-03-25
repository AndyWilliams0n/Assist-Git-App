from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from app.connection_monitor.base import AbstractConnectivityBackend

if sys.platform != 'darwin':
    raise ImportError('MacConnectivityBackend is only supported on macOS')

try:
    from CoreFoundation import (
        CFRunLoopGetCurrent,
        CFRunLoopRun,
        CFRunLoopStop,
        kCFRunLoopDefaultMode,
    )
    from SystemConfiguration import (
        SCNetworkReachabilityCreateWithName,
        SCNetworkReachabilityGetFlags,
        SCNetworkReachabilityScheduleWithRunLoop,
        SCNetworkReachabilitySetCallback,
        SCNetworkReachabilityUnscheduleFromRunLoop,
        kSCNetworkReachabilityFlagsReachable,
    )
    _PYOBJC_AVAILABLE = True
except ImportError:
    _PYOBJC_AVAILABLE = False


def _check_pyobjc() -> None:
    if not _PYOBJC_AVAILABLE:
        raise RuntimeError(
            'pyobjc-framework-SystemConfiguration is required for MacConnectivityBackend. '
            'Install it with: pip install pyobjc-framework-SystemConfiguration'
        )


class MacConnectivityBackend(AbstractConnectivityBackend):
    # Uses SCNetworkReachability for instant OS-level connectivity callbacks.
    def __init__(self, host: str = '8.8.8.8') -> None:
        self._host = host
        self._on_change: Callable[[bool], None] | None = None
        self._connected = True
        self._reachability = None
        self._run_loop = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self, on_change: Callable[[bool], None]) -> None:
        _check_pyobjc()
        self._on_change = on_change
        self._thread = threading.Thread(
            target=self._run,
            name='connection-monitor-mac',
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._run_loop is not None:
            try:
                CFRunLoopStop(self._run_loop)
            except Exception:
                pass

        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

        if self._reachability is not None and self._run_loop is not None:
            try:
                SCNetworkReachabilityUnscheduleFromRunLoop(
                    self._reachability, self._run_loop, kCFRunLoopDefaultMode
                )
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._connected

    def _reachability_callback(self, target, flags: int, info) -> None:
        is_connected = bool(flags & kSCNetworkReachabilityFlagsReachable)

        if is_connected == self._connected:
            return

        self._connected = is_connected

        if self._on_change is not None:
            try:
                self._on_change(is_connected)
            except Exception:
                pass

    def _run(self) -> None:
        self._reachability = SCNetworkReachabilityCreateWithName(None, self._host.encode('utf-8'))
        self._run_loop = CFRunLoopGetCurrent()

        try:
            result, flags = SCNetworkReachabilityGetFlags(self._reachability, None)
            if result:
                self._connected = bool(flags & kSCNetworkReachabilityFlagsReachable)
        except Exception:
            pass

        SCNetworkReachabilitySetCallback(self._reachability, self._reachability_callback, None)
        SCNetworkReachabilityScheduleWithRunLoop(self._reachability, self._run_loop, kCFRunLoopDefaultMode)

        self._ready.set()
        CFRunLoopRun()
