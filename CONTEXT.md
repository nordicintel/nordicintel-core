# NordicIntel Core

The shared language used by NordicIntel applications and provider integrations.

## Language

**Provider**:
An upstream statistical publisher configured through one Adapter.
_Avoid_: Source, backend

**Table**:
A stable, addressable PxApi catalogue resource containing metadata and providing data on request.
_Avoid_: Database table

**Dataset**:
The JSON-stat representation returned for a Table's metadata or requested observations.
_Avoid_: Snapshot, stored observations

**Adapter**:
A provider-family integration that discovers Tables and translates metadata and live data.
_Avoid_: Provider, harvester

**Discovery**:
An Adapter's enumeration of the Tables a Provider publishes in one language. It reports what
is there; nothing infers anything from what is missing.
_Avoid_: Harvest

**Harvest Job**:
One requested traversal of a Provider, or of a single Table, in exactly one language,
retained as its execution history. The language is part of the request because a catalogue
is published per language: a Table carried in Swedish and not in English is absent from the
English catalogue rather than empty in it.
_Avoid_: Run, attempt

**Harvest Item**:
The outcome of processing one upstream Table during a Harvest Job.
_Avoid_: Task, queue item

**Language Metadata**:
The catalogue information and statistical Dataset describing one language of a Table.
It includes that language's labels, classifications, notes, dimensions, categories, and statistical extensions.
_Avoid_: Translation
