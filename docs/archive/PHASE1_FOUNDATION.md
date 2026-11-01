# Phase 1 foundation — historical milestone

The initial foundation was established on 23 October 2026 with Linux x86_64 and Python 3.12. It supplied explicit epochs, stable node/link identities, local OMM input, deterministic topology samples, geometry checks and an engine compatibility decision.

The original route-feasibility workflow used a Python event scheduler, interval-based traffic and immediate shortest-path samples. Those records measured route existence, not packet delivery. Its saved demonstration produced ten generated packets with ten reachable routes; this was not a packet-engine validation or trained RL dataset.

## Retained in the current system

- `constellation/omm.py`: explicit-epoch Walker OMM generation and local loading.
- `constellation/topology.py`: stable geometric graphs, range/occlusion/elevation checks and bounded attachment, subsequently refined by the terminal lifecycle work.
- `constellation/terminals.py`: current acquisition, dwell, hysteresis and reservation rules.
- `constellation/snapshots.py`: physical snapshot/time generation for ns-3 preparation, orbital forecasting and dashboard geometry. It has no Python traffic generator or packet scheduler.
- Geometry regression tests, including retained foundation cases in `tests/test_constellation.py` and later independent checks in `tests/test_geometry_validation.py`.

## Retired on 1 November 2026

The OpenGL viewer, Phase 1 route-feasibility CLI, Python traffic/scheduler implementation, compatibility entry points, static viewer CSV samples, historical pickle and binding probe were removed. The supported interactive interface is Mission Control; the supported packet CLI is `python -m experiments.run`. Shared physical code was extracted rather than discarded.

See the [cleanup record](REPOSITORY_CLEANUP.md), [engine decision](PACKET_ENGINE_DECISION.md), [packet contract](../architecture/PACKET_BACKEND.md), and [current fidelity contract](../research/FIDELITY.md). Initial zero-acquisition/unconstrained-terminal assumptions do not describe the refined orbital fixtures.
