# Recorded evidence

These JSON records and text transcripts are retained scientific/development evidence, not current configuration or command instructions. Their dates, source hashes, result hashes and original filenames are preserved.

| Prefix / file | What it records |
| --- | --- |
| `ns3-probe.json`, `hypatia-build.txt` | Historical packet-engine compatibility decision; the old binding probe is retired |
| `phase2-*` | Controlled forwarding, bounded queues, failures, serialization and TCP checks |
| `phase3*` | Class scheduling, conventional comparisons and native/container checks |
| `phase4*` | Predictive heuristics, forecasts and matched bounded cases |
| `fidelity*` | Terminal/timing refinement, seeded sensitivity cases and platform checks |

Later fidelity records supersede earlier physical assumptions and benchmarks. Consult [current fidelity](../research/FIDELITY.md) and the [archive index](../archive/README.md) before interpreting a number. A Linux-host container check is not a Windows/macOS host validation.

Original source names embedded in hashes/transcripts are provenance. The [cleanup migration table](../archive/REPOSITORY_CLEANUP.md#active-module-migration) maps them to current code. Do not rewrite historical files to match the present layout. New runs/manifests/evidence are generated under `runs/`; deliberately publishing a new record should identify its scenario, software and platform versions.
