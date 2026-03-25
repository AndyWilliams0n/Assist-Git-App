from __future__ import annotations

import sys

from app.connection_monitor.base import AbstractConnectivityBackend

if sys.platform != 'linux':
    raise ImportError('LinuxConnectivityBackend is only supported on Linux')


class LinuxConnectivityBackend(AbstractConnectivityBackend):
    # TODO: Implement using netlink sockets or NetworkManager D-Bus.
    # netlink: bind a NETLINK_ROUTE socket and listen for RTM_NEWROUTE / RTM_DELROUTE messages.
    # D-Bus: subscribe to org.freedesktop.NetworkManager StateChanged signals.
    def start(self, on_change) -> None:
        raise NotImplementedError(
            'LinuxConnectivityBackend is not yet implemented. '
            'Implement using netlink sockets (NETLINK_ROUTE) or NetworkManager D-Bus signals.'
        )

    def stop(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True
