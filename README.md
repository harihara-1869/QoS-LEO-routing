# LEO routing simulator

Phase 2 adds a compiled ns-3 packet backend with dynamic topology, bounded queues, UDP delivery/drop records, runtime route updates and validated TCP Linux Reno cases. The original Phase 1 headless runner remains available for route feasibility. Phase 3 adds Control/Realtime/Bulk scheduling, deadline/fairness metrics and matched conventional routing comparisons. Phase 4 adds orbital/queue forecasts and class-specific predictive heuristic routing. Phase 5 (learned routing) has not started: the corrected environment, congested orbital scenarios and the implementation handoff are in [docs/PHASE5_HANDOFF.md](docs/PHASE5_HANDOFF.md).

## Container setup (Windows and macOS)

The Phase 2 packet backend requires Linux. The pinned `ns3` package only publishes x86_64 Linux wheels, and `packet_backend/build.py` uses Linux compiler and linker flags. On Windows and macOS, run the packet simulator inside the provided Docker image. Install Docker Desktop first.

Build the image once from the repository root:

```bash
docker build --platform linux/amd64 -t leo-sim .
```

Start an interactive shell with the repository mounted at `/workspace`:

```bash
docker run --rm -it --platform linux/amd64 -v "$PWD":/workspace -w /workspace leo-sim
```

For Windows PowerShell, the mount command is:

```powershell
docker run --rm -it --platform linux/amd64 --mount "type=bind,source=$($PWD.Path),target=/workspace" -w /workspace leo-sim
```

Inside the container the two virtual environments from the native instructions already exist, so there is no dependency installation step. Use `/opt/leo-venv/bin/python` for the orbital runner and tests, and leave ns-3 to `/opt/leo-ns3-venv` (the image sets `LEO_NS3_PYTHON`):

```bash
/opt/leo-venv/bin/python compare_policies.py --case all --output runs/phase3
/opt/leo-venv/bin/python run_packet_scenario.py --scenario scenarios/packet_baseline.json --output runs/packet-baseline
/opt/leo-venv/bin/python -m unittest discover -s tests -v
/opt/leo-venv/bin/python run_scenario.py --scenario scenarios/baseline.json --output runs/baseline
```

Notes:

- On Apple Silicon the image runs as `linux/amd64` under emulation. Emulation can be slower; always pass `--platform linux/amd64` so pip finds the ns-3 wheel.
- Files written to `runs/` belong to the container user. On Linux hosts add `--user "$(id -u):$(id -g)"` to keep host ownership.
- The OpenGL viewer needs a display, so it is not available in the container by default. Run `test.py` natively with `requirements-viz.txt` if you need it.
- Windows users can alternatively use WSL2 with Ubuntu 24.04. The native commands below then work unchanged, including the Linux `.venv/bin` paths.

## Phase 2 packet simulation

Run from the repository root. The compiled adapter requires a C++20-capable `g++` and the pinned ns-3 Linux wheel; Python 3.12 / Linux x86_64 was tested. Keep the orbital and ns-3 dependencies in separate virtual environments. On Windows and macOS, use the [container setup](#container-setup-windows-and-macos) instead.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
python3 -m venv .venv-ns3
.venv-ns3/bin/pip install -r requirements-ns3.txt
.venv/bin/python run_packet_scenario.py
.venv/bin/python -m unittest discover -s tests -v
```

The first packet run compiles `packet_backend/engine.cc` into an ignored `runs/build/` cache. Later runs reuse that binary. It links ns-3 directly and does not run the Cppyy interpreter. Use `--ns3-python /path/to/environment/bin/python` or `LEO_NS3_PYTHON` for a different ns-3 environment.

Examples:

```bash
.venv/bin/python run_packet_scenario.py --scenario scenarios/phase2/disappearing_link.json --output runs/link-failure
.venv/bin/python run_packet_scenario.py --scenario scenarios/phase2/tcp_reno_loss.json --output runs/reno-loss
.venv/bin/python run_packet_scenario.py --scenario scenarios/phase2/orbital_transition.json --output runs/orbital-transition
.venv/bin/python -m tools.record_phase2_evidence
```

`scenarios/packet_baseline.json` runs the 200-satellite baseline through the actual packet engine. Explicit small graph fixtures in `scenarios/phase2/` isolate serialization, propagation, congestion, failures and rerouting. The orbital-transition example spans 120 simulated seconds and exercises natural topology changes.

Each output directory contains `results.json` (metrics, UDP outcomes, events and routes), `manifest.json` (versions/source hashes and result hash), `prepared.json` / `engine.plan` (exported topology/workload), `control.json` (live observations/actions), raw TSV logs and `engine.stderr`. `status.json` identifies complete/failed runs. Reusing an output directory overwrites generated results; failed reruns remove prior success files. Tests skip the packet integration cases if the ns-3 environment or compiler is absent; a full Phase 2 validation requires those cases to run.

See [Phase 2 behavior, acceptance evidence and limits](docs/PHASE2_STATUS.md) and [the scenario/controller contract](docs/PACKET_BACKEND.md). Packet accounting distinguishes explicit drops from packets still in flight at the horizon. TCP results report byte delivery and retransmissions separately from UDP datagrams.

## Phase 3 QoS and routing comparisons

Use the same environments or Docker image as above. No new dependencies are required.

```bash
.venv/bin/python compare_policies.py --case all --seed 7 --output runs/phase3
.venv/bin/python run_packet_scenario.py --scenario scenarios/phase3/burst.json --policy congestion --output runs/burst
.venv/bin/python -m tools.record_phase3_evidence
```

`qos: {}` enables weighted byte DRR for Control, Realtime (including STREAMING) and Bulk. Omit it to retain FIFO. The five seeded workloads run with both propagation and congestion-aware Dijkstra using identical scheduling and traffic. Reports include deadline outcomes, class delay/goodput, Bulk fairness/service gaps and route changes. See [Phase 3 status, configuration, measured tradeoffs and Docker validation](docs/PHASE3_STATUS.md). These synthetic smoke comparisons are not the final calibrated research evaluation.

## Phase 4 predictive routing

The predictive controller uses orbital propagation and recent queue/service trends. It has no trained model or weights. Existing environments and the Docker image support it without new dependencies.

```bash
.venv/bin/python run_packet_scenario.py --scenario scenarios/phase4/orbital_transition.json --policy predictive --output runs/predictive-orbit
.venv/bin/python compare_predictive.py --output runs/phase4 --evidence runs/phase4/evidence.json
```

Inside Docker use `python` instead of `.venv/bin/python`. The comparison runs seven scenarios against propagation, congestion, current-QoS, lifetime-only, queue-forecast and combined predictive routing. Add `prediction: {}` alongside `qos: {}` for matched class-routing runs. Outputs include class route tables, forecasts, forecast errors and explicit fallback decisions. See [Phase 4 configuration, contract, evidence and limitations](docs/PHASE4_STATUS.md). Prediction improves some outcomes and worsens others; the report includes both.

## Phase 5 environment — congested orbital scenarios

The connectivity model and link rates were corrected so congestion and handovers occur on the real 200-satellite topology instead of only on five-node fixtures. Satellites now hold two same-plane links plus at most one per adjacent plane, every cross-plane link is reciprocal, and a ground station tracks a bounded number of satellites (`ground_links_per_station`). Link rates are differentiated: `links.isl_capacity_bps` for inter-satellite links and `links.ground_capacity_bps` for ground access.

`scenarios/phase5/` contains normal, burst and overload cases generated by `packet_backend/orbital_workloads.py`. They use reduced absolute rates so congestion appears at a manageable packet count; the ISL:ground ratio is an experimental assumption.

```bash
.venv/bin/python run_packet_scenario.py --scenario scenarios/phase5/normal.json --policy predictive --output runs/phase5-normal
.venv/bin/python compare_predictive.py --scenario scenarios/phase5/overload.json --policies propagation congestion predictive --output runs/phase5-overload
```

Run the full suite with `.venv/bin/python -m unittest discover -s tests -v`. See [the handoff](docs/PHASE5_HANDOFF.md) for the control interface, measured baselines, runtime and memory limits, and the remaining fidelity caveats.

## Terminal and timing fidelity

The refined Phase 5 scenarios use finite satellite ground-beam/ISL terminal budgets, persistent cross-plane pairing, attachment hysteresis and acquisition delays. They start 12 seconds into the orbit so a handover occurs during a short episode. Topology updates every 100 ms and control every 50 ms, making the 300 ms bursts observable. Gateways are endpoints by default in these fixtures; legacy scenarios can explicitly allow gateway transit.

```bash
.venv/bin/python fidelity_experiments.py --quick
.venv/bin/python fidelity_experiments.py --evidence runs/fidelity/evidence.json
```

The full command also tests doubled capacity with fixed or proportionally increased demand. Absolute rates, acquisition times and terminal counts remain configurable assumptions. See [fidelity settings, reference checks and evidence](docs/FIDELITY_UPDATE.md).

## Headless baseline

Tested with Python 3.12 on Linux. No display or runtime downloads are needed after dependency installation.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_scenario.py --scenario scenarios/baseline.json --output runs/baseline
.venv/bin/python -m unittest discover -s tests -v
```

Edit `scenarios/baseline.json` to set the epoch (timezone required), constellation, seed, run duration, update interval, ground stations and flows. The seed is recorded; the current workload is deterministic and does not draw random traffic. `setup.py` is an inherited utility module, not an installation script.

The saved baseline has 200 satellites, two ground stations, a five-second run and a 24 kbps Bulk flow. It generates ten 1500-byte packets and finds a route for all ten. A final partial update interval is supported.

Outputs in the selected run directory:

- `constellation.csv`: generated OMM input with a fixed epoch.
- `results.json`: scenario, time-indexed topology, link distances in km, named route samples and generation/route counts.
- `manifest.json`: result SHA-256, Git revision/dirty flag and installed dependency versions.

Repeat the command with another output directory to compare result hashes. Results are intended to repeat within the pinned software environment; cross-platform floating-point identity is not guaranteed. `datacollection.py` is a compatibility runner for this scenario and no longer overwrites the historical pickle. JSON route samples are shortest-path examples, not RL experience or delivery measurements.

## Visualiser

```bash
.venv/bin/pip install -r requirements-viz.txt
.venv/bin/python test.py
```

`test.py` is the inherited interactive viewer (despite its filename), not a test suite. It shares `LogicalTopology` with headless runs, and uses the existing `customconstellation.csv`, up to 100 satellites and six default stations. It displays live wall-clock orbital time; the headless runner is authoritative for saved experiments. `opengl_sim.py` redirects to the same viewer using `starlink.csv`. A working OpenGL display is required; interactive rendering was not validated in this headless session.

## Historical Phase 1 packet-engine exercise

Keep ns-3 in a separate virtual environment; ns-3 owns all packet timing in this probe.

```bash
python3 -m venv /tmp/leo-ns3-venv
/tmp/leo-ns3-venv/bin/pip install -r requirements-ns3.txt
/tmp/leo-ns3-venv/bin/python tools/probe_ns3.py --baseline runs/baseline/results.json
```

See [the backend decision and evidence](docs/PACKET_ENGINE_DECISION.md), [Phase 1 status and assumptions](docs/PHASE1_STATUS.md), and [the research gap matrix](docs/RESEARCH_GAPS.md). The original [phased plan](LEO_Routing_Phased_Implementation_Plan.md) remains the roadmap; the Phase 2 implementation supersedes the probe-only status in the historical decision record. No A*/Bellman-Ford benchmark is implemented.
