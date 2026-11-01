# APOGEE — Predictive QoS Routing for LEO Networks

APOGEE is a local research simulator and Mission Control web app for studying routing in moving low Earth orbit satellite networks. Design a constellation and ground stations, configure mixed traffic, launch a packet simulation, inspect live metrics, and replay or compare saved runs from one browser application.

The system combines Skyfield/SGP4 orbital geometry, a compiled **ns-3 packet engine**, Python routing policies, and a React/Three.js dashboard. The packet engine owns forwarding, queues, transport and simulated time. The browser displays its observations; it does not simulate network outcomes.

**Current state:** the packet engine, QoS scheduler, predictive heuristics and dashboard are implemented. Learned routing is **not implemented**. Phase 5 remains deferred until the dashboard release gate passes. Remaining implementation belongs to `person_1` through `person_4`; harihara1869's implementation contribution is complete. See [remaining work and ownership](docs/REMAINING_WORK.md).

## Research

The research question is whether **short-horizon link-availability forecasts, queue forecasts and class-specific service safeguards** improve routing during congestion and handovers, without sacrificing Bulk service.

The current implementation provides:

- **Control, Realtime and Bulk** traffic, weighted byte deficit round robin, reserved class queue slots and explicit service targets.
- Six comparable routing policies: propagation Dijkstra, congestion-aware Dijkstra, current-state QoS, link lifetime, queue forecast, and combined predictive QoS.
- Model-based orbital prediction and an EWMA queue forecast. These are heuristics/statistical estimates, with no trained ML model. Forecasts refresh during execution using the allowed observation/model inputs.
- Matched scenarios, seeds, manifests and result hashes; deadline success, delivered-packet latency, goodput, fairness, service gaps, route churn and forecast-error measurements.
- Finite terminal/beam budgets, acquisition outages, attachment hysteresis/dwell, configurable gateway transit, and independent geometry/reference-vector checks.

These are controlled experiments, not a calibrated model of an operator's network. Link rates and terminal parameters are experimental assumptions; public measurement calibration and a statistical evaluation are unfinished. The recorded handover case improves some Realtime outcomes under predictive routing, while the 50 ms Control target remains mostly infeasible. Increased total delivery alone does not establish QoS success or a general policy advantage.

The candidate contribution is the evaluated combination of forecasts and service safeguards. Using PPO, ns-3 or queue-aware routing alone is not a novelty claim. Future learned policies should train offline and use **frozen weights for evaluation**; observations and forecasts can still update. Continuous online learning is outside the current scope.

Read the [research scope and measurement preparation](docs/research/RESEARCH_SCOPE.md), [current fidelity/results](docs/research/FIDELITY.md), and [learning handoff](docs/research/LEARNING_HANDOFF.md). Full literature review, calibration and held-out experiments remain explicit work.

## Setup

Run all commands from the repository root.

### Recommended: Docker

Install Docker with Compose, then run:

```bash
docker compose up --build
```

Open **http://localhost:8080**. Installations with the standalone launcher can use `docker-compose up --build`.

The first build needs internet access. Once built, `docker compose up --no-build` starts with local assets and bundled recorded runs. Stop with Ctrl+C or `docker compose down`; history persists under `runs/dashboard/` through the host `runs/` mount.

- `LEO_DASHBOARD_PORT` changes the local port; `LEO_RUNS_DIR` changes the run directory mount.
- Only `127.0.0.1` is published by default. The app is intended for a single local user.
- The pinned packet engine runs in Linux x86_64 containers. Apple Silicon requires emulation. Linux container execution is verified; Windows/macOS host walkthroughs are still assigned work.
- Keep the mounted run directory writable. Linux users can set the container UID/GID with a Compose override to retain host ownership of generated files.

The same image supports command-line experiments without opening a second web service:

```bash
docker compose run --rm --no-deps mission-control python -m experiments.run --scenario scenarios/phase5/normal.json --policy predictive --output runs/example
```

### Native development: Linux x86_64

Use Python 3.12, a C++20-capable `g++`, and Node.js 24. Keep ns-3 in a separate environment from the orbital/API dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements/dev.txt
python3.12 -m venv .venv-ns3
.venv-ns3/bin/pip install -r requirements/ns3.txt
npm ci --prefix web
npm run build --prefix web
.venv/bin/python -m dashboard
```

Open **http://127.0.0.1:8000**. For hot reload, run `npm run dev --prefix web` in another terminal and use the Vite URL. `LEO_NS3_PYTHON` can select another pinned ns-3 environment. The first packet run compiles the adapter into `runs/build/`.

Requirements are separated by purpose: `requirements/base.txt` for orbital dependencies, `ns3.txt` for the engine, `dashboard.txt` for the app, and `dev.txt` for development/API tests. The old OpenGL and route-feasibility workflows are retired.

## Working with the simulator

1. **Design:** open Constellation Studio, choose a preset, edit orbital parameters, stations, links and traffic, then generate a preview. Preview uses the backend orbital model and has no packet-performance metrics.
2. **Run:** launch with one of the six implemented policies. The job freezes its configuration; additional jobs queue. Engine pause/resume acts at a control boundary. Pause view/Catch up affects presentation only.
3. **Inspect:** follow simulation time separately from wall time. UDP generated = delivered + dropped + in-flight. Latency describes delivered packets; deadline success includes resolved failures and censors not-yet-due outcomes. TCP contributes application bytes to goodput, not UDP datagram counts.
4. **Revisit:** open the Run Library, import existing packet-run artifacts or bundles, replay, seek to events, bookmark a cursor, compare matched runs, and export results. Two real matched runs are bundled for offline demonstrations.

Closing the browser leaves the worker running. Reopening reconnects; shutting down the app interrupts unfinished work and retains its recorded artifacts. Run only one API/supervisor against a run-data directory at a time.

For CLI experiments:

```bash
.venv/bin/python -m experiments.run --scenario scenarios/phase5/normal.json --policy predictive --output runs/normal-predictive
.venv/bin/python -m experiments.compare_baselines --case all --output runs/baselines
.venv/bin/python -m experiments.compare_predictive --scenario scenarios/phase5/normal.json --policies propagation congestion qos_current predictive --output runs/comparison
.venv/bin/python -m experiments.fidelity --quick
```

Each packet run writes the source/prepared scenario, packet results, raw events, controller history, status and a provenance manifest. Dashboard runs also record viewer telemetry and replay data. `runs/` is generated and gitignored; archived evidence under `docs/evidence/` and the bundled demo records are retained. Historical hashes identify their original source paths/revisions and are not rewritten by this cleanup.

See the [packet contract](docs/architecture/PACKET_BACKEND.md), [QoS definitions](docs/architecture/QOS.md), [predictive routing](docs/architecture/PREDICTIVE_ROUTING.md), and [dashboard guide/walkthrough](docs/dashboard/GUIDE.md).

## Phase-wise progress

| Phase | State | Reference |
| --- | --- | --- |
| 1 — Foundation and engine selection | Completed foundation; useful geometry retained, original viewer/headless workflow retired | [Foundation history](docs/archive/PHASE1_FOUNDATION.md), [engine decision](docs/archive/PACKET_ENGINE_DECISION.md) |
| 2 — Packet/network behavior | Implemented: ns-3 forwarding, bounded queues, failures, runtime routing and controlled TCP cases | [Packet contract](docs/architecture/PACKET_BACKEND.md), [validation record](docs/archive/PHASE2_VALIDATION.md) |
| 3 — QoS and conventional baselines | Implemented: class scheduling/workloads and matched comparisons | [QoS contract/evidence](docs/architecture/QOS.md) |
| 4 — Predictive routing | Implemented: orbital/queue forecasts, class routing, safeguards and forecast scoring | [Predictive routing](docs/architecture/PREDICTIVE_ROUTING.md), [fidelity refinement](docs/research/FIDELITY.md) |
| 4.5 — Mission Control | Frontend and local integration implemented; release/performance gates remain | [Dashboard guide](docs/dashboard/GUIDE.md), [release checklist](docs/REMAINING_WORK.md#dashboard-release-gate) |
| 5 — Learned controller | Not started; deferred until dashboard acceptance | [Learning handoff](docs/research/LEARNING_HANDOFF.md) |
| 6 — Measurement calibration | Source/schema preparation only; no acquired validated trace or fitted calibration | [Research scope](docs/research/RESEARCH_SCOPE.md) |
| 7 — Research evaluation | Bounded comparisons exist; batch/resume, held-out statistics and complete ablations remain | [Research/evaluation ownership](docs/REMAINING_WORK.md#person_4--calibration-and-research-evaluation) |
| 8 — Research demonstration/submission | App replay and presentation exist; final calibrated/learned result package remains | [Remaining work](docs/REMAINING_WORK.md), [mentor walkthrough](docs/dashboard/GUIDE.md#mentor-walkthrough-35-minutes) |

## Remaining work

The maintained checklist, dependencies and acceptance evidence are in **[docs/REMAINING_WORK.md](docs/REMAINING_WORK.md)**. Ownership is by complete area:

| Contributor | Area |
| --- | --- |
| `person_1` | Learning environment, safe learned routing, training and checkpoint integration |
| `person_2` | Dashboard frontend, scientific inspection, comparison and presentation |
| `person_3` | Runtime/backend reliability, indexed replay/storage, APIs and deployment |
| `person_4` | Measurement calibration, experiment automation, statistical evaluation and research report |

No remaining implementation or integration duty is assigned to harihara1869. Contributors own code, tests, evidence and documentation for their areas. Final research claims wait for frozen calibration, policies and held-out evaluation; an unfavorable learned-policy result must also be reported.

## Repository layout

```text
constellation/   OMM inputs, topology, terminals and physical snapshots
packet_backend/  Compiled ns-3 engine, routing/forecasting, scheduling and metrics
experiments/     Module-based run/comparison/sensitivity commands
dashboard/       Local API, worker supervision, telemetry and persistent history
web/             Browser application, local assets and frontend tests
scenarios/       Controlled regression fixtures and congested orbital cases
tests/           Packet, geometry, fidelity, prediction and API regression tests
tools/           Acceptance-evidence recording utilities
requirements/    Pinned dependencies by runtime responsibility
docs/            Documentation index, remaining work, contracts, research and evidence
runs/            Generated experiments, build cache and dashboard history (ignored)
```

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
npm test --prefix web
npm run build --prefix web
```

Browser tests require the app to be running and an installed Chromium:

```bash
npm exec --prefix web -- playwright install chromium
LEO_TEST_URL=http://127.0.0.1:8080 npm run test:browser --prefix web
LEO_TEST_URL=http://127.0.0.1:8080 npm run test:compatibility --prefix web
LEO_TEST_URL=http://127.0.0.1:8080 npm run test:live --prefix web
```

Live tests create test runs; use an isolated run directory for verification. `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` optionally selects an existing browser. See the [docs index](docs/README.md) for the current contracts, known limits, historical validation and evidence provenance.

## License and attribution

See [LICENSE](LICENSE). Third-party engine/library licenses and any acquired dataset terms still apply. Bundled textures, fonts and icons have [asset notices](web/public/assets/ATTRIBUTION.md). Measurement data has not been bundled; verify the selected dataset's license before redistribution.
