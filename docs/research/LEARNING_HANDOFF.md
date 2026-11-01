# Learning handoff — Phase 5

**Not implemented; deferred until dashboard release acceptance.** `person_1` owns the complete learning environment, safe policy/training implementation and checkpoints. [REMAINING_WORK.md](../REMAINING_WORK.md) defines acceptance, dependencies and the other contributors' interfaces.

## Starting point

Use `python -m experiments.run` and the existing `packet_backend.controller` policy interface. A fresh run prepares a scenario, starts the compiled ns-3 engine, receives current observations at control boundaries, validates route actions and resumes the same engine clock. An optional observer supplies viewer telemetry; it must not become an extra policy input channel.

The six implemented policies are `propagation`, `congestion`, `qos_current`, `lifetime`, `queue_forecast` and `predictive`. They share one packet model. No PPO weights, training environment or continuously learning policy are shipped. The dashboard's learned-policy/checkpoint fields are future integration surfaces, not a functioning ML backend.

## Current scientific contract

- Observations contain current node/link identities, directed queue state and counters, destinations, normalized QoS settings, and current active-demand metadata where class routing is enabled. Current flow sizes/targets are available; future rates/end times, realized packet outcomes and exported future snapshots are excluded.
- Class routing returns `{(class_id, source_id, destination_id): next_hop_id}`. Conventional two-part route keys are expanded when appropriate. Validation rejects unavailable edges, unknown nodes, dead ends, cycles and forbidden gateway transit.
- Queue forecasts use observed offered/service trends. Orbital forecasts propagate an independent copy of the public geometry/terminal model on the physical update grid. Neither reads future realized packet state.
- Packet time is controlled by ns-3. Physical topology and routing control have separate periods; Python decision wall time is recorded separately and is not added to simulated latency.
- Defaults/semantics are specified in [the packet contract](../architecture/PACKET_BACKEND.md), [QoS definitions](../architecture/QOS.md) and [predictive routing](../architecture/PREDICTIVE_ROUTING.md). Preserve those semantics across heuristic and learned runs.

## Use the refined orbital fixtures

`scenarios/phase5/{normal,burst,overload}.json` are congested **environment fixtures**, despite the directory name; they are not trained-model evidence. The generator is `packet_backend/orbital_workloads.py`.

The current seed-7 setup uses 200 satellites, four stations, five-second episodes, 100 ms physical updates, 50 ms control decisions and a 12 s orbital start offset. It includes finite terminals/ground beams, acquisition/reacquisition, dwell/hysteresis and gateway-transit restrictions. The recorded normal case removes a ground link at 3.90 s and activates a replacement at 4.10 s.

Read [FIDELITY.md](FIDELITY.md) before choosing a learning scale. Earlier one-second-control memory estimates and no-handover figures in [the historical learning notes](../archive/LEARNING_ENVIRONMENT_NOTES.md) are obsolete. Compact controller recording reduces duplication but is not a streaming packet engine; fine updates, route history and packet volume still cost memory/runtime.

```bash
.venv/bin/python -m experiments.run --scenario scenarios/phase5/normal.json --policy predictive --output runs/learning-baseline
.venv/bin/python -m experiments.compare_predictive --scenario scenarios/phase5/normal.json --policies propagation congestion qos_current predictive --output runs/learning-comparison
```

## Implementation constraints

Choose a compact, versioned observation and feasible action representation before training. Candidate-path selection or learned edge costs followed by validated destination trees are possible designs; neither is implemented. Start with measured environment throughput and a small reproducible workload.

Keep invalid-action filtering, loop prevention and a documented heuristic fallback. A single reward must not hide failed urgent deadlines or Bulk starvation. Supply reward components separately, record constraint violations and report infeasible targets rather than silently weakening them.

Train offline; freeze weights, normalization and calibration for held-out evaluation. Refresh state/forecasts during inference without updating weights. Include a current-state-only variant and a bounded simpler RL reference so evaluation can distinguish the value of prediction from the choice of learner. Use independent training/workload seeds and report inference/training cost.

Checkpoints need policy/source hashes, encoder and observation/action versions, normalization, supported topology/features, seed/configuration, calibration ID and fixed/updating weight mode. Reject incompatible manifests before launch. Coordinate the registry/runtime resources with `person_3` and user-facing checkpoint/diagnostic views with `person_2`.

`person_4` owns dataset splits, calibration, final held-out scenarios and statistical evaluation. Retrain or retune affected policies if their training environment changes. The near-infeasible 50 ms Control target and unfavorable results in the current stress cases remain part of the evidence; the learned policy is not assumed to win.
