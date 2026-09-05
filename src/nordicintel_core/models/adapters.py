"""Structural adapter interfaces implemented by provider-family packages."""

from __future__ import annotations

from collections.abc import Mapping
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
    """One Provider integration, for the duration of one job.

    Every method except :meth:`supported_languages` and :meth:`fetch_data` operates in
    the single language the job named. Nothing here chooses a language or reports which
    languages a Table has: a Table appearing in the inventory of a language is the whole
    of that statement.
    """

    async def supported_languages(self) -> list[str]:
        """Every language this Provider publishes, for scheduling and for validation."""
        ...

    async def discover(self, scope: DiscoveryScope) -> DiscoveryResult:
        """Enumerate the scope, in ``scope.language``."""
        ...

    async def should_refresh(
        self, entry: DiscoveryEntry, stored: LanguageState | None, *, force: bool
    ) -> bool:
        """Decide whether this Table's metadata has to be fetched again.

        ``stored`` is None when this Table has never been accepted in this language. Only
        the adapter knows what its own marker means, so only the adapter answers this.
        """
        ...

    async def fetch_metadata(
        self, entry: DiscoveryEntry, language: str
    ) -> MetadataFetchResult:
        """Return this Table's complete representation in one language.

        One call, one language, one result. Failure is raised, not represented as an
        empty or partial list, so a caller never has to decide what a missing element in
        a returned collection was supposed to mean.
        """
        ...

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
