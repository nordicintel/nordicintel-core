"""Shared pagination bounds for repository reads."""

from __future__ import annotations


def page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset cannot be negative")
    return limit, offset
