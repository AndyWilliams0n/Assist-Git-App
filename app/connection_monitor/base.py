from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class AbstractConnectivityBackend(ABC):
    @abstractmethod
    def start(self, on_change: Callable[[bool], None]) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...
