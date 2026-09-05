"""Errors shared across application and adapter boundaries."""

from __future__ import annotations

from typing import Any


class NordicIntelError(Exception):
    """Base class for safe, typed NordicIntel failures."""


class ConfigurationError(NordicIntelError):
    """A provider or adapter configuration is invalid."""


class AdmissionError(NordicIntelError):
    """A database-backed operation was rejected before execution."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class OwnershipLost(NordicIntelError):
    """A worker no longer owns the database session protecting its job."""


class UpstreamError(NordicIntelError):
    """A sanitized failure while communicating with a provider."""

    def __init__(self, message: str, *, code: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class UpstreamTransportError(UpstreamError):
    """The upstream request failed before a response was available."""


class UpstreamResponseError(UpstreamError):
    """The upstream returned a non-success response."""


def sanitized_diagnostic(code: str, message: str, **details: Any) -> dict[str, Any]:
    """Build a JSON-safe diagnostic without accepting bodies or credentials by convention."""
    return {"code": code, "message": message, **details}
