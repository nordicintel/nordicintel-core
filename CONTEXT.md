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
The JSON-stat representation of a Table's metadata or observations. In persistence, a dataset row
holds the stable identity and lifecycle of a Table.
_Avoid_: Snapshot, stored observations

**Adapter**:
A provider-family integration that discovers Tables and translates metadata and live data.
_Avoid_: Provider, harvester

**Discovery**:
An Adapter's enumeration of Tables in a requested provider scope, together with whether that
enumeration is authoritative for absence-based retirement.
_Avoid_: Harvest

**Harvest Job**:
One requested traversal of a Provider or a single Table, retained as its execution history.
_Avoid_: Run, attempt

**Harvest Item**:
The outcome of processing one upstream Table during a Harvest Job.
_Avoid_: Task, queue item

**Language Metadata**:
The labels, notes, ordered dimensions, ordered categories, and comparison state for one language of
a Table.
_Avoid_: Translation
