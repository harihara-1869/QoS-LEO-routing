# LEO routing simulator

Phase 1 provides a repeatable orbital topology and distance-weighted Dijkstra baseline. It records **route feasibility**, not packet delivery: queues, forwarding, handovers and transport validation are Phase 2 work. There is no trained RL controller.

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

## Established packet-engine exercise

Keep ns-3 in a separate virtual environment; ns-3 owns all packet timing in this probe.

```bash
python3 -m venv /tmp/leo-ns3-venv
/tmp/leo-ns3-venv/bin/pip install -r requirements-ns3.txt
/tmp/leo-ns3-venv/bin/python tools/probe_ns3.py --baseline runs/baseline/results.json
```

See [the backend decision and evidence](docs/PACKET_ENGINE_DECISION.md), [Phase 1 status and assumptions](docs/PHASE1_STATUS.md), and [the research gap matrix](docs/RESEARCH_GAPS.md). The original [phased plan](LEO_Routing_Phased_Implementation_Plan.md) remains the roadmap. No A*/Bellman-Ford benchmark is implemented.
