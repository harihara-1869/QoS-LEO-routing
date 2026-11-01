# Phase 5 handoff — simulator state for the learned routing controller

**Historical design notes:** these measurements and interface dimensions predate the terminal/timing refinement. Use [the current learning handoff](../research/LEARNING_HANDOFF.md), [fidelity contract](../research/FIDELITY.md) and [remaining-work assignments](../REMAINING_WORK.md) for implementation. Old measurements below are retained as evidence of the development sequence, not current performance budgets. Code paths/examples use the reorganized package names; recorded hashes remain historical.

## 1. Why the simulator was corrected

The original simulator was numerically sound but did not present a decision problem worth learning. Measured on the checked-in orbital runs before this pass:

- The busiest queue on any link in the 120-second orbital transition peaked at **1 packet**, with mean occupancy 0.0 and zero drops. A congestion-aware router had nothing to react to.
- Satellite neighbour counts ranged from **3 to 6**, because each satellite independently picked its nearest satellite in each adjacent plane without a one-to-one terminal matching. Real satellites have a fixed terminal budget, and degree distribution *is* the path diversity a routing policy exploits.
- Both ground stations held **4 and 6 simultaneous satellite links**, so a station could load-balance across six paths and the handover constraint disappeared.
- All 458 links had **identical capacity** (10 Mbps) regardless of whether they were inter-satellite or ground access.

The correction addresses each of these. It does not claim the simulator is now physically faithful; section 9 lists what is still missing.

## 2. What changed

### 2.1 Connectivity is a fixed terminal budget

`constellation/topology.py` now pairs adjacent planes with **one offset per plane pair**, chosen to minimise the summed distance across that pair. Each satellite therefore holds:

- two same-plane links (ring neighbours, gated by range and Earth clearance),
- at most one cross-plane link into each adjacent plane.

Every cross-plane link is reciprocal by construction. The two seam planes carry one cross-plane link instead of two, so their satellites have degree 3 and interior satellites degree 4. Measured on the 200-satellite, 10-plane baseline: **ISL degree is 3 for the 40 satellites in the seam planes and 4 for the other 160**, and the two satellites serving a ground station each carry one additional ground link. Independent nearest-neighbour selection was removed because adjacent planes cross near the inclination latitude, which produced one-sided links and hubs.

### 2.2 Ground access is bounded

A ground station no longer connects to every satellite above the elevation mask. It ranks visible satellites by elevation and keeps the best `ground_links_per_station` (default 1, Phase 5 scenarios use 2). Measured on the baseline with two stations: exactly one link per station instead of 4 and 6.

### 2.3 Link rates are differentiated

`LogicalConfig` gained `isl_capacity_bps` (default 100 Mbps) and `ground_capacity_bps` (default 20 Mbps). `constellation/snapshots.py` writes the capacity of each link into every topology snapshot, and `packet_backend/scenario.py` carries it into the ns-3 plan, so ISL and ground links differ inside the packet engine.

For orbital scenarios the rates come from `links.*_capacity_bps`; `network.capacity_bps` now only defaults explicit-topology graphs. The 5:1 ratio is an experimental assumption; the absolute values are not, and section 9 explains why.

### 2.4 Congested orbital scenarios exist

Before this pass, every scenario where congestion occurred was a five-node diamond with uniform 1 Mbps links, and every realistic orbital scenario was idle. `packet_backend/orbital_workloads.py` and `scenarios/phase5/` close that gap: three seeded cases on the full 200-satellite topology where offered load meets or exceeds ground-access capacity.

Measured on the checked-in fixtures (seed 7, 5 s, one control tick per second):

| Case | Packets generated | Dropped at queue overflow | Peak queue (of 40) |
| --- | ---: | ---: | ---: |
| normal | 6,225 | 2,091 | 39 |
| burst | 5,864 | 2,126 | 40 |
| overload | 11,826 | 6,834 | 40 |

All overflow drops are on ground-access links, in the direction of travel. That is the intended placement: the inter-satellite mesh is provisioned well above the access rate, so the bottleneck is where it physically is.

### 2.5 `results.json` no longer duplicates the event log

A congested run was writing **45 MB** of `results.json` because the full raw event list was embedded as well as written to `events.tsv`. The serialized result now omits `events`; in-process callers still receive it, and the manifest hash is computed over the file that is actually written. Checked-in runs now produce 2.6–4.5 MB.

### 2.6 Independent geometry checks

`tests/test_geometry_validation.py` validates the geometry against separately written arithmetic rather than itself:

- **Two-body propagation vs SGP4.** A Kepler propagator built from the OMM mean elements is compared with Skyfield's SGP4 out to 300 s. Absolute offset is tens of km because mean and osculating elements differ; the *rate* must agree, and drift stayed under 25 km over five minutes (orbital motion covers roughly 2,280 km in that time).
- **Elevation.** A hand-written WGS84 geodetic-to-ECEF transform plus ENU projection agrees with Skyfield's `altaz()` to **1.2e-12 degrees** across six stations including both poles. This validates the geodesy and the elevation gate, which is what this project computes.
- **Occlusion.** `link_clear_of_earth` is compared with an independent chord calculation over angles from 1° to 179°.
- **Link geometry.** Graph edge weights equal direct Euclidean distances, every ISL respects the range limit, capacities match the configured value by link class, and an explicit `distance_km` converts to `delay_s` at exactly 299,792.458 km/s.
- **Topology structure.** ISL degree is bounded at 4, cross-plane links never skip a plane, no satellite holds two links into one plane, ground links are bounded, no parallel or self links exist, and the station picks the highest-elevation satellite.

Full suite after these changes: **77 tests, no skips, 31 seconds**.

## 3. What the controller must respect about simulation semantics

**Time.** All times are simulated seconds from the scenario epoch, in a half-open interval `[0, duration_s)`.

**Topology is piecewise constant.** The engine receives a list of snapshots, each holding the complete active link set at that time. A link missing from a snapshot is down. Between snapshots, delay and availability do not change.

**Control is synchronous and does not consume simulated time.** The ns-3 process pauses inside an event, writes the current state to stdout, blocks reading the route response, then resumes. Python decision time is measured separately in `manifest.json` and never appears in simulated delays. Consequence for evaluation: inference cost must be reported as wall time; it does not degrade the simulated QoS.

**Decisions happen at control ticks.** `control_interval_s` adds observations between topology snapshots, holding the last observed topology. A topology change and a control tick at the same timestamp produce one update. In the Phase 5 fixtures that is 5 decisions per episode.

**Failures are handled by the engine, not the policy.** On a down transition both directions' waiting queues are flushed (labelled `link_down_queued`) and every transmission already serializing or propagating is invalidated (`link_down_in_flight`), including after restoration. New traffic uses the new route or records `no_route`. IPv4 TTL bounds transient loops left by topology changes between hops. A cyclic or incomplete route response is rejected and fails the run.

**Transport.** UDP datagrams are paced at the offered rate; TCP is a finite bulk stream under `ns3::TcpLinuxReno` with SACK disabled. TCP and its ACKs are always Bulk. The class scheduler is weighted byte deficit round robin with reserved per-class queue slots; it is work-conserving, non-preemptive, and unused reservations are not borrowed.

## 4. The control interface

### 4.1 Observation

A policy is a callable receiving one dictionary. Exact keys, as produced by `packet_backend/controller.py`:

| Key | Contents |
| --- | --- |
| `time_s` | Current simulated time. |
| `nodes` | Ordered node names; list index is the node ID. |
| `links` | Active links: `id`, `a`, `b`, `capacity_bps`, `queue_packets`, `delay_s`. Directed capacity is the same in both directions. |
| `queues` | One entry per link and direction: `link_id`, `direction` (0 is a→b, 1 is b→a), `packets`, `bytes`, and `classes`. |
| `queues[].classes` | Control/Realtime/Bulk, each with `packets`, `bytes`, `arrived_bytes`, `served_bytes`, `rejected_bytes` (cumulative). |
| `destinations` | Destination node IDs used by the configured flows. |
| `qos` | Normalised QoS config: scheduler, weights, quantum, targets. |
| `mtu_bytes` | Maximum wire packet size used for buffer bounds. |
| `active_flows` | Currently offered flows: `id`, `src`, `dst`, `class_id`, `flow_type`, `protocol`, `size`, `deadline_s`, `min_goodput_bps`. Excludes flows whose start time has not arrived and zero-rate UDP declarations. |

Phase 5 fixture dimensions: 204 nodes, 388 links, **776 queue entries** (388 × 2), 3 destinations, and 1,827 route entries in the action.

The observation deliberately excludes future snapshots, future flow rates, flow end times and realised delivery outcomes. A regression test changes a future workload and topology suffix and asserts every earlier observation and action is unchanged.

### 4.2 Action

Return a dictionary mapping `(class_id, source_node, destination_node)` to `next_hop_node`, with class IDs Control 0, Realtime 1, Bulk 2. A legacy `(source, destination)` key is accepted and copied to all three classes; mixing key formats is rejected.

Validation is strict. Unknown endpoints, a next hop that is not on a currently active link, a source equal to its destination, a forwarding cycle, or a chain that dead-ends before the destination all raise and fail the run. Omitting a key is allowed and simply leaves that destination unreachable.

### 4.3 Plugging in a policy

`experiments.run.run(scenario, output, policy=...)` accepts:

- a registered name: `propagation`, `congestion`, `qos_current`, `lifetime`, `queue_forecast`, `predictive`;
- any callable taking the observation and returning the action dict;
- a `PredictivePolicy` instance, whose settings must match the scenario's `prediction` block.

Each call starts a fresh ns-3 process, so reset isolation is structural. Stateful policies additionally get `policy.reset()` before the run; a test asserts a reused stateful policy produces identical results on two runs.

### 4.4 Forecasts

A custom callback receives only the observation. To use forecasts as *inputs*, instantiate the predictors yourself, as `packet_backend/controller.py::resolve_policy` does:

```python
from packet_backend.prediction import OrbitalForecaster, QueueForecaster, settings
from constellation.omm import get_satellite_data

config = settings(plan['prediction'])
queues = QueueForecaster(config)
orbital = OrbitalForecaster(get_satellite_data(csv_file=output / 'constellation.csv'),
                            scenario['epoch'], scenario['links'],
                            scenario['ground_stations'], config)

queue_forecasts = queues.predict(observation)    # per link/direction/class
link_forecasts = orbital.predict(observation)    # per link: availability, delay, lifetime
```

Forecasts are causal. The orbital forecaster rebuilds a separate topology from the OMM elements and never reads the prepared future snapshots. Its lifetime is reported as an interval with a lower bound, and a null upper bound means "no disappearance observed within the horizon", not "infinite".

## 5. Scenarios

`packet_backend/orbital_workloads.py` generates complete configuration dictionaries; `scenarios/phase5/{normal,burst,overload}.json` are the checked-in seed-7 fixtures, and a test asserts the generator still reproduces them.

Shared settings: 10 planes × 20 satellites at 53°, 550 km; four gateway stations (India, USA, Brazil, Australia) with two tracking antennas each; 10 Mbps ISLs and 2 Mbps ground links; 40-packet queues; five-second runs with one-second control ticks; class routing and forecasts enabled with horizons inside the run window.

The three cases differ only in offered load: `normal` at unit scale, `burst` at 0.6 with two short urgent bursts, `overload` at 1.9. Reproduce any of them with:

```bash
.venv/bin/python -m experiments.run --scenario scenarios/phase5/normal.json --policy predictive --output runs/phase5-normal
.venv/bin/python -m experiments.compare_predictive --scenario scenarios/phase5/overload.json \
    --policies propagation congestion predictive --output runs/phase5-overload
```

The Phase 2–4 fixtures remain valid and are still useful as regression and ablation cases, but their recorded hashes and metrics in the older status documents predate the connectivity and capacity corrections and are not comparable.

## 6. Measured baselines to beat

Seed 7, five-second episodes, identical traffic, scheduler and control times; only the routing policy changes. `delivered` counts UDP datagrams delivered out of the generated total; `drop` is queue overflow; `churn` is the sum of per-flow route changes.

| Case | Policy | Delivered | Dropped | Churn | Control | Realtime | Bulk |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| normal | propagation | 4,134 | 2,091 | 0 | 1,946 | 569 | 1,619 |
| normal | congestion | 4,291 | 1,934 | 20 | 1,946 | 609 | 1,736 |
| normal | predictive | **4,762** | **1,463** | 17 | 1,953 | 890 | 1,919 |
| burst | propagation | 3,738 | 2,126 | 0 | 1,554 | 549 | 1,635 |
| burst | congestion | 3,818 | 2,046 | 32 | 1,549 | 552 | 1,717 |
| burst | predictive | **4,038** | **1,826** | 25 | 1,670 | 593 | 1,775 |
| overload | propagation | 4,992 | 6,834 | 0 | 3,171 | 412 | 1,409 |
| overload | congestion | 5,141 | 6,685 | 20 | 3,145 | 459 | 1,537 |
| overload | predictive | **5,436** | **6,390** | 18 | 3,310 | 572 | 1,554 |

p95 delivery delay on the `normal` case, in seconds:

| Policy | Control | Realtime | Bulk |
| --- | ---: | ---: | ---: |
| propagation | 0.078 | 0.161 | 0.371 |
| congestion | 0.084 | 0.163 | 0.359 |
| predictive | 0.072 | 0.139 | 0.299 |

Three things to note, because they shape what a learned policy should be asked to do:

1. **The ordering predictive > congestion > propagation holds in every case**, on delivered packets and on Realtime/Bulk p95. This is the first time the engineered baseline has headroom rather than a tie at "everything delivered".
2. **Congestion-aware routing slightly worsens Control p95** (0.084 vs 0.078) while improving Bulk. Shortest-path keeps Control on the least-delayed path; the congestion policy trades some Control latency for Bulk throughput. A learned policy that optimises one weighted average will likely reproduce this trade-off badly; class-aware objectives matter.
3. **Fallbacks fire 4–5 times per episode** in the predictive policy, and route churn is lower than the congestion baseline (17 vs 20), which suggests the switching penalty is doing real work.

## 7. Designing the PPO environment

### 7.1 Episode and step mapping

One episode is one `run()` call. Reset is inherent: every call spawns a new engine process, and any stateful policy is reset first. A step is one control tick, and there are five per episode at the current setting.

If five decisions per episode is too few for PPO, **decrease `control_interval_s` instead of increasing duration**. Control ticks add decisions without adding packets: at `control_interval_s: 0.25` a five-second episode has 20 decisions and the same traffic. Duration is the expensive axis; see section 8.

### 7.2 Per-step reward is available from cumulative counters

The observation does not include delivery outcomes, but each queue exposes cumulative `arrived_bytes`, `served_bytes` and `rejected_bytes` per class and direction. Differencing them between consecutive ticks gives, for every link and class: bytes offered, bytes transmitted, and bytes rejected. That is a viable dense per-step reward without waiting for the episode to end. Episode-level ground truth is available afterwards from the returned dictionary (per-flow delivered/dropped/in-flight, delay mean/p95/p99, deadline counts and success ratio, goodput, Jain fairness, starvation intervals, route changes, forecast errors).

Be aware that `served_bytes` counts dequeue for transmission, not end-to-end delivery, and that link-down queue flushing is not counted as overflow or service.

### 7.3 Action space

The raw action is one next hop for every `(class, source, destination)`: 1,827 entries on the Phase 5 fixtures. Treating that as a flat discrete action is not workable. Two practical reductions:

- **Learned edge weights over the existing tree builder.** Score each directed link, then run Dijkstra per class and destination exactly as `packet_backend/predictive.py::tree` does. The action becomes 776 real values with a feasible-by-construction result, and `validate_routes` still applies as a check.
- **Next-hop selection for the flow's source only.** Restrict the decision to sources with active demand (at most 5 flows here, usually fewer distinct sources), each choosing among its ≤4 current neighbours. The destination trees for intermediate nodes remain Dijkstra. This is the smallest action space that still changes routing.

Invalid-action handling is already strict; there is no need to build masking from scratch, but a policy that returns cycles will fail the run rather than be penalised. Prefer masking to rejection during training.

### 7.4 Observation encoding

776 queue entries × 3 classes × 5 fields is large for a flat MLP input. The quantities that carry most of the signal are per-link: current per-class waiting bytes, cumulative rejected-byte rate, capacity, delay, and predicted lifetime if you compute it. A per-link summary (388 × a handful of features) plus a small per-flow block is a reasonable first encoding. A graph network over the link list is the natural fit and avoids the fixed-node-count assumption, but it is not required to start.

### 7.5 Determinism and comparability

Runs are deterministic for a fixed seed, scenario and environment; result hashes repeat, and the tests enforce it. Wall times are excluded from the result hash. Compare policies only on matched scenarios, as `experiments/compare_predictive.py` does, which records a scenario hash alongside each result hash.

## 8. Hard limits measured on this machine

These numbers are engineering limits, not fidelity claims, and they constrain how large an episode can be.

| Measure | Observed |
| --- | --- |
| 5 s `normal`, propagation | 12.8 s wall, 239 MB peak RSS |
| 5 s `normal`, congestion | 15.4 s wall, 260 MB |
| 5 s `normal`, predictive | 18.1 s wall, 358 MB |
| 5 s `burst`, propagation | 11.6 s wall, 224 MB |
| 5 s `overload`, propagation | 15.4 s wall, 270 MB |
| `results.json` size | 2.6–4.5 MB |
| `events.tsv` size | 7.7–10.7 MB |
| Full suite | 31 s, 77 tests |

Memory grows roughly linearly with generated packets because every queue change, transmission and drop becomes an event. A 12-second prototype at about 82 Mbps total offered load was killed by the OS before completing; that run would have generated on the order of 100,000 packets. **Treat roughly 20,000 packets per episode as the practical ceiling** on this machine and keep five-second episodes unless you have measured otherwise.

Two consequences for PPO: do not hold hundreds of full result dictionaries in memory at once, and prefer in-process extraction of the reward and metrics over retaining whole `results.json` objects. If training needs longer episodes, the first change to make is a streaming or aggregate-only result mode; that does not exist yet.

## 9. Remaining fidelity gaps — state these in any claim

The correction pass fixed the two problems that made the decision problem degenerate. It did not make the simulator a measurement-calibrated model of Starlink.

- **Rates are reduced.** Ten Mbps ISLs and 2 Mbps ground links are one to three orders of magnitude below operational links. The ratio is an experimental assumption; the scale is chosen so congestion appears at a tractable packet count. Absolute throughput, delay under load and drop counts are not predictions of a real network.
- **No link budget or loss model.** A link is up or down. There is no attenuation, rain fade, pointing error, interference, or terminal allocation limit. The only packet loss is queue overflow and link removal.
- **The optical/terminal model is a budget, not a design.** Degree 3–4 matches a four-terminal spacecraft, but acquisition, tracking and pointing feasibility are not modelled. The opt-in IOL cone is a geometry heuristic.
- **Orbital forecasting is a same-model oracle.** The forecaster and the simulator share the same SGP4 topology code, so availability accuracy measures consistency, not prediction skill. In the `normal` case it scored 3,880 samples at 100% availability accuracy and zero delay error by construction. Any claim that the learned policy exploits forecasts must be qualified accordingly.
- **Queue forecasting still loses to persistence.** Measured MAE versus persistence: 82.3 vs 47.1 bytes (`normal`), 40.3 vs 20.5 (`burst`), 167.3 vs 55.7 (`overload`). The predictive policy's advantage therefore comes from class-aware routing and safeguards, not from forecast accuracy. A learned policy trained to imitate or exploit the forecaster is exploiting a weak signal.
- **No measurement calibration.** Phase 6 has not started; simulated delay and loss distributions have never been compared with a LENS trace. There is no empirical grounding yet.
- **Geometry validation is partial.** Our geodesy, elevation gate, occlusion, distance-to-delay arithmetic and propagation *rate* are independently validated. The GCRS-to-Earth-fixed frame rotation is Skyfield's, not independently reimplemented, and SGP4 is not cross-checked against an external ephemeris service.
- **Traffic is synthetic.** Paced UDP plus finite TCP bulk, with hand-chosen rates and targets. There is no arrival process, no flow-size distribution and no measured demand model.
- **Historical scope:** this note preceded the dashboard. Current delivered features and remaining phases are listed in the repository README and remaining-work roadmap.

## 10. Files changed in this pass

| File | Change |
| --- | --- |
| `constellation/topology.py` | Reciprocal single-offset cross-plane pairing; bounded ground links; `isl_capacity_bps`, `ground_capacity_bps`, `ground_links_per_station` with validation; capacities attached to graph edges. |
| `constellation/snapshots.py` | Topology snapshots carry per-link `capacity_bps`. |
| `packet_backend/orbital_workloads.py` | New: seeded congested orbital scenario generator. |
| `scenarios/phase5/{normal,burst,overload}.json` | New: checked-in fixtures. |
| `experiments/run.py` | Serialized result excludes the raw event list; manifest hash covers the written file. |
| `tests/test_geometry_validation.py` | New: 15 independent geometry and topology tests. |
| `tests/test_orbital_workloads.py` | New: 10 generator and congested-run tests. |
| `docs/architecture/PACKET_BACKEND.md` | Orbital capacity fields, connectivity rule, event serialization. |
| `docs/archive/PHASE1_FOUNDATION.md` | Connectivity and ground-access assumptions updated. |
| `README.md` | Phase 5 environment section. |

Not changed, deliberately: the ns-3 adapter, the QoS scheduler, the forecast arithmetic and the route validator. The corrections are in the topology and scenario layer, so the packet engine's existing validation still applies unchanged.

## 11. Suggested first three tasks for the PPO work

1. **Build the environment shell and prove it reproduces a baseline.** Wrap `run()` in reset/step, drive `qos_current` or `congestion` through it, and check the per-flow counts match a direct run. If they do not match, the environment is adding behaviour the simulator does not have.
2. **Establish the action reduction before training.** Implement the next-hop-only action over active flow sources and confirm it can reproduce the congestion baseline's decisions when given a hand-coded cost. Training against an action space that cannot express the baseline is a common way to waste a week.
3. **Reproduce the trade-off, not just the mean.** The predictive baseline improves Realtime and Bulk while slightly worsening Control p95. Use the class metrics already emitted (deadline success per class, p95/p99, Bulk fairness and starvation) and report the trade-off. A policy that wins on total delivered while worsening Control deadlines has not beaten the heuristic in the sense the project cares about.

## 12. Reproduction commands

```bash
# Full suite: 77 tests, about 31 s
.venv/bin/python -m unittest discover -s tests -v

# Geometry and topology checks only
.venv/bin/python -m unittest tests.test_geometry_validation -v

# Congested scenario checks only
.venv/bin/python -m unittest tests.test_orbital_workloads -v

# One congested orbital run per policy
.venv/bin/python -m experiments.run --scenario scenarios/phase5/normal.json --policy predictive --output runs/phase5-normal
.venv/bin/python -m experiments.run --scenario scenarios/phase5/normal.json --policy congestion --output runs/phase5-congestion

# Matched three-policy comparison, writes comparison.json per case
.venv/bin/python -m experiments.compare_predictive --scenario scenarios/phase5/overload.json \
    --policies propagation congestion predictive --output runs/phase5-overload
```

Inside the Docker image, replace `.venv/bin/python` with `/opt/leo-venv/bin/python`.
