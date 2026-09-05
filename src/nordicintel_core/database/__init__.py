"""Optional PostgreSQL repositories."""

from .connection import connect
from .metadata import MetadataRepository, canonical_slug
from .providers import ProviderRepository
from .queue import HarvestRepository, ScheduleRepository

__all__ = [
    "HarvestRepository",
    "MetadataRepository",
    "ProviderRepository",
    "ScheduleRepository",
    "canonical_slug",
    "connect",
]
