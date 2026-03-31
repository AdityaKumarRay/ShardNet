"""Consistent domain error types."""

from collections.abc import Mapping
from typing import Any


class ShardNetError(Exception):
    """Base error shape for all domain-level failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


class ConfigurationError(ShardNetError):
    """Raised when runtime configuration is invalid."""


class ProtocolError(ShardNetError):
    """Raised when a peer message violates protocol expectations."""


class TransferError(ShardNetError):
    """Raised when a piece or file transfer fails."""
