"""
ironclaw.memory.base
~~~~~~~~~~~~~~~~~~~~
Abstract base classes for IronClaw memory backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ironclaw.core.message import Message


class MemoryBackend(ABC):
    """Base class for all memory stores."""

    @abstractmethod
    def append(self, message: Message) -> None: ...

    @abstractmethod
    def history(self, limit: int | None = None) -> list[Message]: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def __len__(self) -> int: ...


class KeyValueBackend(ABC):
    """Base class for key-value persistent stores."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def keys(self) -> list[str]: ...

    @abstractmethod
    def clear(self) -> None: ...
