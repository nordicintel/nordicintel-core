"""Provider configuration contracts."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator

from ._base import CoreModel

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ProviderDefinition(CoreModel):
    """Public and operational configuration for one provider."""

    id: str
    label: str = Field(min_length=1)
    description: str | None = None
    website: str | None = None
    region: str | None = Field(default=None, min_length=2, max_length=2)
    adapter_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("id", "adapter_type")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _IDENTIFIER.fullmatch(normalized):
            raise ValueError("must match [a-z0-9][a-z0-9._-]*")
        return normalized

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("secret_refs")
    @classmethod
    def validate_secret_refs(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not name.strip() for key, name in value.items()):
            raise ValueError("secret names and references must be nonempty")
        return value
