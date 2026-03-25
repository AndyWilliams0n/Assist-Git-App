from __future__ import annotations

import sys

from app.connection_monitor.monitor import ConnectionMonitor


def _create_backend():
    if sys.platform == 'darwin':
        from app.connection_monitor.backends.mac import MacConnectivityBackend
        return MacConnectivityBackend()

    if sys.platform == 'linux':
        from app.connection_monitor.backends.linux import LinuxConnectivityBackend
        return LinuxConnectivityBackend()

    raise RuntimeError(
        f'No connectivity backend available for platform: {sys.platform}. '
        'Add a backend in app/connection_monitor/backends/ and register it here.'
    )


connection_monitor = ConnectionMonitor(_create_backend())

__all__ = ['ConnectionMonitor', 'connection_monitor']
