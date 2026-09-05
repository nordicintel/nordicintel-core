# Adapter integration

An adapter package implements `AdapterFactory` and `NordicIntelAdapter` from
`nordicintel_core.models`. The host resolves secret references, owns an `httpx.AsyncClient`, wraps it
in `nordicintel_core.http.HttpClient`, and injects both configuration and HTTP access into the
factory.

Adapters own provider-specific URLs, authentication, discovery, request construction, response
parsing, and comparison-marker semantics. They return normalized core models and never receive a
database connection. Live-data requests always contain explicit category codes; expression parsing
and selection expansion happen before adapter dispatch.

`DiscoveryResult.authoritative` may be true only when its provider-wide scope was completely
enumerated. Core rejects absence-based retirement for incomplete or single-table discovery.

HTTP retries are opt-in per operation. An adapter may mark a GET or a read-only POST as
`retry_safe=True`; mutating or ambiguous operations must keep the default.
