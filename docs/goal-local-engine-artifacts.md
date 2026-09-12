# Local engine artifacts for Goal comparisons

Rating protocol version 3 supports one administrator-installed candidate binary and
one public Git baseline. It is limited to the existing common-model fixed-move
acceptance and STC policies. The same network, options, opening, clock, benchmark,
startup and result checks still apply. Versions 1 and 2 retain their existing meaning.

The candidate source is a closed object with `kind=local_private`, `artifact_id`,
`binary_sha256`, `name` and `bench`. The name must be `goal-local-<artifact_id>`;
the repository field must be empty. The binary SHA-256 is an executable identity,
not a Git commit. No URL, filesystem path, source text or build settings are accepted.
The baseline keeps the version 2 public source object.

The server stores the opaque source URI
`goal-local-v1:<artifact_id>:<binary_sha256>` in the existing Engine record. It rejects
any conflicting name or artifact ID, preserves existing records, and returns the
complete identity on version 3 GET. Older GET versions reject local artifacts rather
than omit their identity. An unknown create or stop outcome requires reconciliation
using its saved test ID; this protocol adds no replay operation.

Before qualification, the fixed maintenance adapter must install these two files
under the worker's existing protected root while workers are quiescent:

- `Engines/goal-local-<artifact_id>-<binary_sha256>.exe`
- `PrivateEngines/<artifact_id>.json`, containing exactly `schema_version=1`,
  `descriptor` (the closed source object), and `binary_size`.

The worker rejects missing, nonregular, linked, altered or oversized files and checks
the full executable hash on every load. It also revalidates the fixed-move workload.
Loading never downloads, compiles, installs, repairs or falls back to a public engine.
Installation and builds belong to the coordinator's protected one-shot adapters;
this protocol itself grants no installation or dispatch authority.

Private sources, build recipes, paths and raw compiler output stay outside this
repository and the server protocol. Operator-only provenance must bind the source,
recipe, compiler, binary, benchmark, compatibility checks and measured clock contract.
Deploy this source and its new client module to both server and worker before making
a version 3 request. A fresh compatible qualification is required before production.
Rollback may restore code while preserving installed artifacts and all test records;
older code cannot reconcile local records and must not redispatch them.
