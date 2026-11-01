# Remaining work — four-contributor ownership

Updated 1 November 2026. This is the maintained roadmap and acceptance checklist. The root [README](../README.md#phase-wise-progress) records phase progress; detailed contracts are indexed in [docs/README.md](README.md).

**harihara1869 has finished their implementation contribution.** All work below belongs to `person_1`, `person_2`, `person_3` or `person_4`, by complete area. These are end-to-end implementation responsibilities, including code, regression tests, reproducible evidence and documentation. They are not validation-only assignments.

The existing foundation, packet engine, QoS layer, predictive heuristics and Mission Control app are the starting point. Phase 5 learned-controller implementation/training remains **deferred until the dashboard release gate passes**. Interface design and independent measurement/reliability work can proceed first.

## Ownership and boundaries

| Owner | Complete area | Main locations / deliverable |
| --- | --- | --- |
| `person_1` | Learning environment and learned routing | New learning package, policy adapters, reproducible training/checkpoints, safe inference through the existing policy interface |
| `person_2` | Frontend and scientific demonstration | `web/`, scenario/run/replay UX, policy/checkpoint views, meaningful diagnostics and mentor presentation |
| `person_3` | Backend/runtime, storage and deployment | `dashboard/`, worker/control bridge, indexed artifacts, durable job/API contracts and local packaging |
| `person_4` | Calibration and research evaluation | `experiments/`, measurement/analysis tooling, fixed datasets/splits, statistical results and final research report |

New learning, measurement and analysis packages are proposed work, not implemented directories. Shared core changes in `constellation/` and `packet_backend/` are owned by the contributor whose feature needs them: runtime/telemetry by `person_3`, learned routing by `person_1`, and calibrated physics/metric changes by `person_4`. Preserve one packet engine, one policy interface and documented metric semantics. Coordinate cross-area schemas directly; no work is routed back to harihara1869.

## person_1 — learning environment and learned routing

Scope: Phase 5 and the policy/checkpoint portions of the final demonstration. Start implementation/training after the dashboard gate; prepare the observation/action/checkpoint design before it.

- [ ] Implement reset/step/termination around the authoritative packet engine, with seeded episodes and bounded observations. Measure environment throughput and memory before selecting training scale.
- [ ] Define versioned observation encoding and a manageable action representation, such as feasible candidate paths or learned edge costs followed by validated destination trees. Include class, destination, current queue/capacity state and optional forecasts.
- [ ] Preserve the causal boundary: no future workload schedules, actual future topology records or realized evaluation labels in policy inputs. Viewer telemetry must remain separate from reward/observation channels.
- [ ] Implement invalid-action masking, loop/dead-end rejection and a documented heuristic fallback. Preserve explicit QoS requirements beyond one weighted reward.
- [ ] Implement reproducible offline PPO training, a current-state-only learned variant, and a bounded simpler RL reference. Save seeds, optimizer/configuration versions, reward components and training history.
- [ ] Register callable checkpoints with observation/action/encoder versions, feature normalization, scenario compatibility, hashes and fixed/updating weight mode. Reject incompatible manifests before a job starts; supply that validation to the backend registry.
- [ ] Supply inference, reward-component and action diagnostics through policy-independent run artifacts. Keep weights frozen for held-out validation/evaluation; continuous online weight updates remain deferred.
- [ ] Deliver trained artifacts and matched evaluation hooks to `person_4`; expose checkpoint metadata to `person_3` and display requirements to `person_2`.

**Done when:** saved checkpoints run safely through the existing CLI/API and dashboard surface; reset/step and causality tests pass; independent training seeds are reproducible; matched heuristic/current-state/simpler-RL comparisons retain failures and unfavorable outcomes. A policy need not beat the heuristic to constitute an honest completed experiment.

Read [learning handoff](research/LEARNING_HANDOFF.md), [predictive routing](architecture/PREDICTIVE_ROUTING.md), and [fidelity limits](research/FIDELITY.md).

## person_2 — dashboard frontend and demonstration

Scope: remaining frontend work in Phase 4.5 and final mentor-facing views in Phase 8. Own the frontend implementation and user-facing behavior; `person_3` supplies storage/runtime APIs.

- [ ] Extend scientific inspection from topology events to congestion, deadline failures, route changes, predicted lifetime and routing/fallback explanations. Identify forecasts, installed routes and actual packet paths separately; never fill missing historical layers with invented data.
- [ ] Integrate indexed replay windows/events from `person_3`, including loading/error/reconnect states, synchronized globe/charts/inspector, persisted annotations and navigation to a named event.
- [ ] Expand history filtering for scenario, seed, class, date and policy/checkpoint. Surface scenario/model/policy compatibility differences in comparison; keep whole-episode summaries distinct from cursor metrics.
- [ ] Add checkpoint selection and learned-policy status through the capability registry when `person_1` supplies a real adapter. Add training progress/rewards and evaluation views only when real job data exists; no fake PPO switch or training charts.
- [ ] Make measured traces, calibrated simulations and recorded demos visibly distinguishable. Show fixed versus updating weights and calibration/checkpoint IDs in final result views.
- [ ] Measure rendering FPS on the actual demo computer at the refined 200-satellite scenario. Implement adaptive quality, route/congestion isolation and camera focus/follow where needed; verify reduced motion, keyboard/focus behavior, contrast and projector readability.
- [ ] Finish a 3–5 minute guided presentation covering design, a live run, a handover/congestion inspection, replay, matched comparison and an unfavorable result. Integrate final research bundles from `person_4`.

**Done when:** the mentor workflow is reproducible from one browser, loading/partial/error states remain honest, the primary demo view sustains the agreed rendering budget (target at least 30 fps on the actual demo machine), and browser/accessibility/visual evidence is recorded. Final learned/calibrated views consume genuine artifacts.

Read [dashboard guide](dashboard/GUIDE.md), [design/acceptance specification](dashboard/DESIGN.md), and [metric definitions](architecture/QOS.md).

## person_3 — backend, persistence and deployment

Scope: remaining platform work in Phase 4.5 and the runtime/storage integration required by Phases 5/8. Own backend features and deployment, not just platform testing.

- [ ] Replace whole-file normalized replay reads with byte-offset/chunk indexes and bounded metric/event queries. Keep exact state transitions and windowed/downsampled series versioned; preserve original artifacts and unsupported-layer capability flags.
- [ ] Strengthen durable queue/lifecycle transitions and requested/applied/rejected command acknowledgements. Test pause/cancel races, preparation/finalization cancellation, worker failure, application restart, browser disconnection and queue fairness.
- [ ] Bound telemetry collection and delivery independently of simulation/control cadence. Coalesce replaceable snapshots for slow clients, persist important events, and make stream sequence gaps/reconnect behavior explicit.
- [ ] Extend the policy/job resources to store checkpoint, encoder, calibration, scenario and source versions. Invoke `person_1`'s manifest compatibility checks; add training-job lifecycle/stream resources when the learning implementation is available.
- [ ] Persist labels/bookmarks/comparison settings outside immutable scientific results. Maintain stable import identity, artifact-root validation, portable exports and supported packet-schema adapters.
- [ ] Benchmark controller/telemetry overhead, wall time, replay query latency and peak memory against headless **packet-engine** execution (the retired Phase 1 workflow is not a baseline). Set explicit budgets and scale/resource limits from measurements.
- [ ] Complete long-run crash/reconnect/cancellation soak tests and verify no owned Python/ns-3 process remains after cancellation/shutdown. Preserve completed artifacts through failed attempts and restarts.
- [ ] Finish Docker-host walkthroughs on Windows/macOS and Apple Silicon where available, writable-volume/ownership guidance, offline restart, dependency/license documentation and operational troubleshooting. Keep one API supervisor per data directory and local-only binding by default.

**Done when:** indexed replay and durable lifecycle behavior have failure/restart evidence; metrics reconcile with authoritative output; overhead/resource budgets are documented; and one-command installation, offline restart and persisted history are verified on each platform claimed as supported.

Read [packet contract](architecture/PACKET_BACKEND.md), [dashboard design](dashboard/DESIGN.md), and [cleanup/migration record](archive/REPOSITORY_CLEANUP.md).

## person_4 — calibration and research evaluation

Scope: Phase 6, the complete Phase 7 experiment/analysis system, and the scientific report/bundles for Phase 8. Own working ingestion, calibration and evaluation code as well as the results.

- [ ] Complete the full-text literature comparison: forecasts/horizons, classes/targets, action feasibility, safeguards, simulator fidelity and train/test separation. Record exact source revisions and narrow the contribution accordingly.
- [ ] Acquire a bounded public measurement subset with provenance, hashes, endpoints, timestamp units, collection settings and redistribution terms. Implement timestamp/unit/loss parsing; preserve directional loss and distinguish RTT from one-way measurements and missing values.
- [ ] Define chronological calibration/validation/final-test splits before fitting. Match the observable measurement path, including explicit aggregate access/terrestrial effects where justified. Do not infer internal queues/routes or unidentifiable physical parameters from endpoint RTT alone.
- [ ] Implement fitting and held-out validation for supported parameters. Quantify temporal behavior, latency tails and availability, then freeze/export a versioned calibration with an uncertainty/limitations report. Coordinate any required physics/metric extensions and tests.
- [ ] Build resumable experiment automation with run inventories, failure/retry accounting, matched scenario/calibration/policy versions, independent workload and training seeds, and resource-aware execution.
- [ ] Evaluate all six heuristic/conventional policies plus `person_1`'s simpler RL, current-state-only learned and forecast-enabled learned variants. Include normal/burst/overload, handovers, explicitly synthetic failures and held-out traffic, station pairs and a constellation setting.
- [ ] Run ablations removing topology prediction, queue forecasting, QoS safeguards and route-change penalties. Study physical/control timestep convergence, forecast uncertainty, target feasibility and capacity/demand sensitivity; never silently relax targets to improve a result.
- [ ] Report uncertainty intervals and favorable/unfavorable cases for delivery, p95/p99 survivor delay, deadline success, goodput, fairness, backlogged service gaps, route churn and forecast error. Include training/inference cost, simulator runtime and memory scaling.
- [ ] Freeze the final evaluation manifest and publish reproducible tables/plots, limitations and inherited-component attribution. Deliver selected normal/congested/disrupted runs and calibration/checkpoint provenance to `person_2`/`person_3` for replay/export.

**Done when:** a traceable dataset/split/frozen-calibration pipeline and resumable evaluation system exist; every research claim has reproducible matched evidence and uncertainty; measurement/synthetic sources are distinct; and the final report includes cases where the proposed approach loses. Endpoint calibration does not establish a claim about an operator's internal routing or real-world policy improvement.

Read [research scope/trace preparation](research/RESEARCH_SCOPE.md), [fidelity results](research/FIDELITY.md), and [learning handoff](research/LEARNING_HANDOFF.md).

## Dashboard release gate

`person_2` owns the frontend evidence and `person_3` owns the backend/runtime evidence. They record acceptance in this file; Phase 5 implementation/training can then resume under `person_1`.

- [ ] One-command setup, engine readiness, offline restart and persistent history are verified after the final platform changes.
- [ ] Studio → real launch → visible pre-completion metrics → acknowledged engine pause/resume → view pause/catch-up → cancel/reconnect/restart → replay/export/compare pass against the packaged app.
- [ ] Exact counters/final summaries, ECEF geometry, historical missing fields and matched-condition warnings pass correctness checks. Viewer collection leaves deterministic packet outcomes unchanged and reveals no extra future information to policies.
- [ ] Indexed replay, bounded telemetry and resource/overhead budgets pass the chosen 200-satellite demonstration workload; actual demo-machine rendering meets the agreed budget.
- [ ] Failure/partial/command states, keyboard/reduced-motion/WebGL fallback and the future policy/checkpoint contract have test evidence. The offline guided walkthrough includes an unfavorable QoS outcome.

Existing implementation has evidence for much of the functional path; unchecked boxes are final release acceptance, not a claim that all these features are absent.

## Dependencies and delivery order

1. **Start in parallel:** `person_2` completes frontend diagnostics/performance; `person_3` hardens indexing/runtime/deployment; `person_4` acquires data and builds calibration/evaluation tooling. `person_1` specifies the future learning/manifest interface while implementation remains deferred.
2. **After dashboard acceptance:** `person_1` implements the learning environment/policies. `person_2` and `person_3` integrate genuine checkpoint/training artifacts through the agreed contracts. Baseline evaluation and calibration continue independently.
3. **Before final comparisons:** freeze dataset splits, calibration, targets, metrics, policy/checkpoint versions and held-out scenarios. Retrain/retune affected models if calibration changes their environment. `person_4` runs the same frozen conditions for every policy.
4. **Final delivery:** `person_4` supplies research results and report; `person_1` supplies callable frozen checkpoints; `person_3` supplies reproducible bundles/runtime; `person_2` delivers the integrated demonstration. Each contributor resolves defects in their area.

Keep scale manageable rather than dropping accounting correctness, strong baselines, the learned comparisons, uncertainty or honest limitations. Update this checklist when work is accepted; avoid separate competing ownership lists.
