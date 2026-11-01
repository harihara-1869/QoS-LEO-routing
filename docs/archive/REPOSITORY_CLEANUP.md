# Repository cleanup — 1 November 2026

The repository now supports the Mission Control dashboard and compiled packet simulator. The old standalone viewer and Phase 1 headless route-feasibility workflow are retired. Existing run bundles, bundled demos and raw checked-in evidence are preserved.

## Active module migration

| Former root module | Current module | Responsibility |
| --- | --- | --- |
| `setup.py` | `constellation/omm.py` | OMM loading and constellation generation; not package installation |
| `logic_module.py` | `constellation/topology.py` | Physical graph construction and attachment constraints |
| `terminal_model.py` | `constellation/terminals.py` | Terminal reservations, acquisition and ground selection |
| `sim_man.py` | `constellation/snapshots.py` | Extracted geometry/time sampler, `TopologySnapshots`; old traffic/clock code removed |
| `run_packet_scenario.py` | `experiments/run.py` | Authoritative packet-run CLI/API |
| `compare_policies.py` | `experiments/compare_baselines.py` | Matched conventional baseline comparisons |
| `compare_predictive.py` | `experiments/compare_predictive.py` | Matched heuristic/forecast comparisons |
| `fidelity_experiments.py` | `experiments/fidelity.py` | Terminal/timing and capacity/demand sensitivity experiments |

Imports and manifest source paths use the new packages. Run scripts as modules from the repository root, for example `python -m experiments.run`; there are no root compatibility wrappers.

Pinned dependencies moved into `requirements/{base,ns3,dashboard,dev}.txt`. One root `Dockerfile` now builds the full app and also supports CLI command overrides; the separate dashboard/shell-image Dockerfiles are consolidated. Compose keeps the local app entry point.

## Removed material

- Legacy entry points `test.py`, `opengl_sim.py`, `run_scenario.py` and `datacollection.py`.
- The retired Python `traffic_module.py` and `schedule_core.py`, plus their five scheduler/traffic/route-feasibility tests and old baseline scenario.
- Viewer-only dependencies and the unused `customconstellation.csv`, `starlink.csv`, `tiedtest.csv` and `rl_training_data.pkl` sample artifacts.
- The superseded Cppyy compatibility-probe sources. Their historical numeric records remain under `docs/evidence/`.

Useful foundation geometry tests remain; active orbital/terminal logic is under `constellation/`. Existing `runs/`, measurement/reference test fixtures and research evidence were not removed.

## Documentation migration

The root README now describes the project, research question, setup/working, phase status and remaining work. `docs/README.md` indexes topical architecture/dashboard/research guides. Historical phase/probe notes are under `docs/archive/`; measurement preparation is merged into the research scope. `docs/REMAINING_WORK.md` is the maintained ownership/checklist for four other contributors; harihara1869 has no remaining implementation assignment.

Historical source paths inside raw evidence and bundled run hashes are intentionally unchanged. They identify the files that produced those records; changing them would misrepresent provenance. Use the migration table above to locate today's implementation. Regenerated evidence belongs under `runs/` unless intentionally publishing a new versioned record.

## Verification

The reorganized native suite passes 91 tests, including packet/TCP behavior, class scheduling, causality, geometry, terminal lifecycle and dashboard data/API checks. Five obsolete workflow tests were removed, rather than deleting useful physical/packet coverage. The renamed orbital packet CLI reproduced exactly the saved normal-predictive scientific result hash. The consolidated image builds, and packaged Chromium checks pass Studio preview, import/replay/comparison, offline/reduced-motion/WebGL fallback, real launch/pause/resume/reconnect, cancellation and partial history. Six frontend tests and the production build pass; local Markdown links and referenced headings resolve.
