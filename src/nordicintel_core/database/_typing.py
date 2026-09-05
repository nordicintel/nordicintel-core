"""Internal row and connection aliases."""

from __future__ import annotations

from typing import Any, TypeAlias

Row: TypeAlias = dict[str, Any]
Connection: TypeAlias = Any


def page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset cannot be negative")
    return limit, offset
