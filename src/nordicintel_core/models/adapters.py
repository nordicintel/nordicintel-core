"""Structural adapter interfaces implemented by provider-family packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from nordicintel_core.jsonstat import JsonStatDataset

from .data import ExplicitSelection
from .harvest import DiscoveryEntry, DiscoveryResult, DiscoveryScope, LanguageState
from .metadata import MetadataFetchResult
from .provider import ProviderDefinition


@runtime_checkable
class AsyncHttpClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        retry_safe: bool = False,
        **kwargs: Any,
    ) -> Any: ...


@runtime_checkable
class NordicIntelAdapter(Protocol):
    async def resolve_languages(self, requested: Sequence[str] | None) -> list[str]: ...

    async def discover(self, scope: DiscoveryScope) -> DiscoveryResult: ...

    async def languages_to_refresh(
        self,
        entry: DiscoveryEntry,
        stored: Mapping[str, LanguageState],
        requested: Sequence[str],
        *,
        force: bool,
    ) -> list[str]: ...

    async def fetch_metadata(
        self, entry: DiscoveryEntry, languages: Sequence[str]
    ) -> list[MetadataFetchResult]: ...

    async def fetch_data(
        self, native_table_id: str, selection: ExplicitSelection
    ) -> JsonStatDataset: ...


@runtime_checkable
class AdapterFactory(Protocol):
    async def create(
        self,
        provider: ProviderDefinition,
        secrets: Mapping[str, str],
        http: AsyncHttpClient,
    ) -> NordicIntelAdapter: ...
