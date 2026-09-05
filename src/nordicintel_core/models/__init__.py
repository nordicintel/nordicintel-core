"""Public model and protocol contracts."""

from nordicintel_model.jsonstat import JsonStatDataset

from .adapters import AdapterFactory, AsyncHttpClient, NordicIntelAdapter
from .data import DimensionSelection, ExplicitSelection
from .harvest import (
    Diagnostic,
    DiagnosticStage,
    DiscoveryEntry,
    DiscoveryResult,
    DiscoveryScope,
    HarvestItem,
    HarvestJob,
    HarvestRequest,
    HarvestSchedule,
    ItemStatus,
    JobStatus,
    JobTrigger,
    LanguageState,
    QueueCount,
)
from .metadata import (
    AvailabilityStatus,
    LanguageMetadata,
    MetadataFetchResult,
    ServingMode,
    TableCatalogMetadata,
    TableLanguageMetadata,
    TableRecord,
    TableSearchResult,
    deterministic_hash,
)
from .provider import ProviderDefinition
from .statistical import Link, PathElement, TableCategory, TimeUnit

__all__ = [
    "AdapterFactory",
    "AsyncHttpClient",
    "AvailabilityStatus",
    "Diagnostic",
    "DiagnosticStage",
    "DimensionSelection",
    "DiscoveryEntry",
    "DiscoveryResult",
    "DiscoveryScope",
    "ExplicitSelection",
    "HarvestItem",
    "HarvestJob",
    "HarvestRequest",
    "HarvestSchedule",
    "ItemStatus",
    "JobStatus",
    "JobTrigger",
    "JsonStatDataset",
    "LanguageMetadata",
    "LanguageState",
    "Link",
    "MetadataFetchResult",
    "NordicIntelAdapter",
    "PathElement",
    "ProviderDefinition",
    "QueueCount",
    "ServingMode",
    "TableCatalogMetadata",
    "TableCategory",
    "TableLanguageMetadata",
    "TableRecord",
    "TableSearchResult",
    "TimeUnit",
    "deterministic_hash",
]
