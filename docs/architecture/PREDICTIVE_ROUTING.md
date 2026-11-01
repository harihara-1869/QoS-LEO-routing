# Phase 4 — Predictive QoS routing

Implemented by **harihara1869**. Bounded acceptance tables below predate the latest physical refinement; see [current fidelity/results](../research/FIDELITY.md). The packet backend now supports physics-based link forecasts, a statistical queue forecast and a class-specific heuristic routing controller. Six interchangeable policies run against the same packet engine and scheduler. No ML training or learned weights are involved in this phase.

## Run

Use the existing native environments or Docker image; no dependencies were added.

```bash
.venv/bin/python -m experiments.run --scenario scenarios/phase4/orbital_transition.json --policy predictive --output runs/predictive-orbit
.venv/bin/python -m experiments.compare_predictive --output runs/phase4 --evidence runs/phase4/evidence.json
.venv/bin/python -m unittest discover -s tests -v
```

Inside Docker, replace `.venv/bin/python` with `/opt/leo-venv/bin/python` (or `python`, already on the image's PATH). For a shorter comparison:

```bash
python -m experiments.compare_predictive --scenario scenarios/phase4/burst.json --policies congestion qos_current queue_forecast predictive --output runs/phase4-burst
```

The full suite has seven scenarios × six policies = 42 runs. Each scenario gets `scenario.json`, separate policy directories and `comparison.json`. Per-run manifests retain source/dependency/result hashes and runtime measurements. Failed runs raise and record failed status; the affected comparison summary is removed before rerunning. The optional suite evidence is written only after all selected scenarios complete; use a fresh evidence filename when retaining separate attempts.

## Policies and configuration

| Policy name | Route cost and forecast signals |
| --- | --- |
| `propagation` | Existing propagation Dijkstra. |
| `congestion` | Existing current aggregate queue-pressure Dijkstra. |
| `qos_current` | Class-aware current queue estimates, switching penalty and service safeguards; no forecast used in route cost. |
| `lifetime` | Same class-aware heuristic plus orbital availability/lifetime and propagation forecasts. If the orbit model is unavailable, explicitly falls back to congestion routing. |
| `queue_forecast` | Class-aware heuristic with forecast queue pressure; current link availability. |
| `predictive` | Combined queue and orbital forecasts, service safeguards and switching penalty. On explicit graphs, queue forecasting remains available and link lifetime is labelled unknown. |

The `qos_current` control helps separate the effect of forecasts from the effect of class-aware routing. Diagnostics calculate queue forecasts for the heuristic variants even when the selected mode does not use them in its route cost.

Add `"prediction": {}` and `"qos": {}` to a scenario to use the versioned class-routing interface, including for matched conventional baselines. Selecting a new heuristic policy also enables that interface and requires an explicit QoS configuration. Defaults are:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `queue_horizon_s` | 0.1 | Queue forecast look-ahead. |
| `orbital_horizon_s` | 15 | Maximum orbital look-ahead; longer lifetimes are right-censored. |
| `orbital_step_s` | 5 | Spacing of orbital feasibility samples; at most 100 steps. |
| `ewma_alpha` | 0.5 | Weight of the latest observed arrival/service rate sample. |
| `link_guard_s` | 0.1 | Additional required link lifetime. |
| `change_penalty_s` | 0.005 | Added route cost for changing an installed next hop. |

`control_interval_s` still determines decision frequency. Choose horizons aligned with control times for direct forecast scoring. The orbital fixture uses five-second decisions/queue forecasts, a 15-second orbital horizon and a five-second lifetime guard; the synthetic load cases use 50 ms decisions and the default 100 ms queue horizon. These fixed experimental settings have not been optimized against held-out data.

## Forecasts and information boundary

`packet_backend/prediction.py` implements two independent predictors:

**Orbital forecast.** A separate `LogicalTopology` instance uses the known OMM orbit elements, epoch, ground stations and link rules. It propagates the model at the current time and future sample times. It does not read `prepared.json`'s future snapshots, traffic schedules, future observations or result logs. For each currently available link it records predicted availability, propagation delay and the interval bracketing its first sampled disappearance. No predicted disappearance within the horizon means a finite lower bound and a null upper bound, not infinite lifetime. Sampling can miss a down/up episode between samples; the bracket assumes no such missed crossing. The next available future sample supplies the propagation estimate used in route cost.

An explicit graph has no orbital model. Its future snapshot list is **not** treated as a predictor. Lifetime is null/unknown, with its source labelled accordingly. Sudden non-orbital failures remain unpredictable from this model. Newly predicted links are not installed ahead of actual availability.

**Queue forecast.** The ns-3 class queues expose cumulative offered wire bytes, dequeued service bytes and rejected wire bytes. Recent counter differences produce arrival/service rates, smoothed by an EWMA. Arrival counters include overflow attempts so a full queue does not conceal excess demand. Estimated service combines observed service with the DRR share among recently active classes, rescaled to link capacity. The forecast is:

```text
predicted backlog = current backlog + (estimated arrival rate − estimated service rate) × horizon
```

It is clipped between zero and the class reservation's packet-limit × maximum wire-packet size. That is a byte upper bound; actual buffer capacity depends on packet sizes. A cold predictor uses current backlog. An observed down transition discards trend history for that link; restoration starts cold. Estimates and history update at every control tick, while configuration remains fixed.

The formula assumes recent traffic/service trends persist. Routing itself changes future arrivals, and bursts violate the assumption. This model is deliberately measured against a persistence forecast (future queue = current queue) on the **same realised trajectory**. Its error must not be interpreted as a counterfactual forecast of a different routing policy.

Current observations include active flow class, endpoints, packet size and service targets; zero-rate UDP declarations are excluded from active demands. They exclude future flows' rates, stop times and realised traffic. Destination IDs remain the static configured destination catalogue. The causal regression test changes a future workload/topology suffix and checks that every earlier observation, forecast and action stays identical.

## Route decisions and safeguards

`packet_backend/predictive.py` builds one destination tree per class. The estimated link cost combines propagation, class waiting time and serialization of a representative packet. Packet size uses the largest currently declared payload for the class/destination. An observed competing class's average queued packet size supplies an approximate non-preemptive blocking term. Exact serializer state and DRR deficits are not exposed, so this is an estimate rather than a latency bound.

The controller:

1. Filters links whose predicted usable lifetime is too short for the class budget plus guard. The budget is the tightest active deadline for that class/destination, or the queue horizon for Bulk.
2. For Bulk, filters paths through links whose nominal weighted capacity divided by the number of active Bulk flows falls below the requested floor. This is a conservative capacity check, not a per-flow reservation.
3. Runs Dijkstra with a penalty for changing an existing next hop.
4. Checks active demands against estimated end-to-end delay and the selected path's link lifetimes. If the switching penalty prevents a satisfactory choice, retries without it.
5. When requirements still cannot be met, replaces the **entire class/destination tree** with current-state congestion routing and records the reason. Replacing the whole tree avoids loops that could arise from splicing incompatible route trees.

Every installed class tree is validated for available edges, complete forwarding chains and loops. A fallback is not a declaration that a target is met: deadline/floor risk and unreachable outcomes remain recorded. Constraints are checked on the chosen trees; this bounded heuristic is not an exhaustive constrained-path optimizer.

Positive Bulk DRR weight and its reserved queue space continue to protect class service. The capacity screen adds a routing safeguard, but cannot guarantee equal throughput or per-flow starvation freedom. Global active Bulk counts can make this screen conservative for disjoint routes. End-to-end checks use active flow declarations, not each in-flight packet's remaining deadline; stricter per-packet deadline routing is a future extension.

## Backend contract extension

The internal generated plan is now `LEO4`. Regenerate it through the Python runner. Scenario JSON remains schema 1; result schema is 4 for class-routing runs, 3 for existing QoS runs and 2 for FIFO runs.

- Legacy callbacks can still return `{(source, destination): next_hop}`. In a class-routing run these actions are copied to all three classes.
- Class-aware callbacks return `{(class_id, source, destination): next_hop}` with class IDs Control 0, Realtime 1, Bulk 2. Mixed key formats are rejected.
- `packet_backend/class_routing.h` selects a separate ns-3 static table using the packet's class tag at the source and forwarding hops. TCP data and ACKs use Bulk and retain stable source identities across reroutes.
- `control.json` retains `class_routes`, current counters, active demands, forecast samples, decision estimates and fallback reasons. `routes` remains the Bulk table for older readers; class-aware readers must use `class_routes`.
- `results.json` retains class route snapshots, actual packet paths, per-flow route-change counts and the existing QoS outcomes. Route changes count the entire recorded run, including ticks outside a flow's active window.
- `class_route` events use source as `item`, destination as `a`, next hop as `b`, installed/removed as `value`, and class ID as `detail`.
- Cumulative class counters are `arrived_bytes`, `served_bytes`, `rejected_bytes`. Service counts dequeue for transmission, not end-to-end delivery. Link-down queue flushing is not counted as overflow or service; failure traces provide that separate accounting.

Built-in stateful policies reset between runs. A supplied `PredictivePolicy` object's settings must match the scenario. For custom callbacks/forecasters, retain their source and configuration with the experiment, as for the earlier callback contract.

## Forecast scoring and evidence

`packet_backend/prediction_metrics.py` scores forecasts **after** simulation, at exactly matching future observation timestamps. Missing samples and forecasts beyond the run horizon are unscored, with null error when there are no matches. Queue reports include overall and per-class MAE, persistence MAE and busy-sample MAE so empty queues cannot hide all error. Orbital reports include false availability/unavailability, propagation error and lifetime error when both predicted and observed first disappearance are available.

Orbital scoring compares predictions against the same sampled physical model used by the simulator. Perfect agreement is a consistency check, not independent validation of satellite ephemerides, real equipment failures or physical-terminal allocation. Lifetime error is also conditional on matched sample times; it is not continuous-time loss timing.

**52 tests passed with no skips, both natively and inside the existing linux/amd64 Docker image. All 42 matched-run result hashes agree between native and Docker execution.** Tests cover queue arithmetic and warm-up/reset, forecast scoring/censoring, early reaction to a growing queue, switching costs and deadline override, explicit fallback risks, loop rejection, orbital elevation-loss bracketing, real class-specific packet forwarding, overflow counters, future-data isolation, state reset and TCP recovery. All 35 previous tests remain included.

Evidence: [native tests](../evidence/phase4-native-tests.txt), [Docker tests](../evidence/phase4-docker-tests.txt), [platform result hashes](../evidence/phase4-platform-check.json), [seven-case/six-policy comparison bundle](../evidence/phase4.json). Windows/macOS hosts and Apple Silicon emulation were not tested here. The existing Dockerfile and dependency pins were sufficient.

Selected seed-7 results, with scheduling and traffic fixed:

| Case / policy | Control deadline success | Realtime deadline success | Bulk goodput, kbps | Sum of flow route changes |
| --- | ---: | ---: | ---: | ---: |
| Burst — congestion | 74.8% | 44.1% | 259.2 | 128 |
| Burst — current QoS | 75.6% | 47.0% | 259.2 | 134 |
| Burst — predictive | 69.1% | 45.0% | 259.2 | 144 |
| Hotspot — congestion | 100% | 100% | 1293.6 | 270 |
| Hotspot — current QoS | 100% | 100% | 1310.4 | 148 |
| Hotspot — predictive | 100% | 100% | 1300.8 | 168 |
| Overload — congestion | 89.2% | 6.5% | 535.2 | 272 |
| Overload — current QoS | 91.2% | 7.1% | 537.6 | 176 |
| Overload — predictive | 98.7% | 7.8% | 535.2 | 142 |

Low/normal load delivers every packet under all policies; prediction adds route churn in these cases. The unexpected explicit-link failure causes two packet losses under every policy, illustrating that the controller is not reading future failure events. On explicit graphs, combined and queue-only outcomes coincide; lifetime-only uses its recorded fallback.

For combined prediction, queue MAE is **163.5 bytes versus 123.5 bytes for persistence during bursts**, and **1130.4 versus 351.0 under overload**. Thus the simple rate forecast does not beat persistence in aggregate error on this suite. Its routing effect still differs: overload Control performance improves, while abrupt bursts expose overshoot and worse deadlines. The current-QoS control also shows that some gains come from class-aware decisions rather than forecasting.

In the 200-satellite orbital case, the affected ground link disappears at 90 s. Lifetime/combined routing switches Bulk at **75 s** and Control/Realtime at **80 s**; conventional/current-QoS routing changes at **90 s**. All policies deliver all **2282** packets here, so the proactive handover is demonstrated without claiming a delivery improvement. The combined predictor scores 30,377 matched availability samples correctly and 47 uncensored lifetime estimates with zero sampled-time error, as expected for the shared deterministic model.

Controller time in this native orbital run was about 0.05 s for congestion, 0.86 s for current QoS and 2.78 s for the combined predictor across 24 decisions. These are single-run engineering measurements, not a scaling or training-throughput benchmark; wall times remain outside deterministic result hashes.

## Handoff to Phase 5

Phase 4 is complete as a reproducible engineered baseline with measured successes and failures. Forecasts, class route actions, safeguards and per-class outcomes are ready for the learning-environment work. Keep a current-state-only learned variant and compare against both current-QoS and predictive heuristics. Train offline, freeze learned weights for evaluation, and continue refreshing observations/forecasts during inference. No continuously learning model has been introduced.

The bounded suite is not a calibrated research evaluation or proof of general improvement. Phase 7 still needs held-out workloads, multiple seeds, uncertainty, ablations and larger-scale costs. Physical-terminal modelling, independent orbital checks and measurement calibration remain the earlier documented limitations.
