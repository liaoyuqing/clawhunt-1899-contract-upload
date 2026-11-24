"""Domain errors used across the service."""

from __future__ import annotations


class ConfigurationError(RuntimeError):
    """Raised at start-up when mandatory configuration is missing or blank."""


class StorageError(RuntimeError):
    """Raised when the object storage adapter cannot fulfil a request."""


class DispatchError(RuntimeError):
    """Raised by the recognition-task dispatch stub when delivery fails."""
