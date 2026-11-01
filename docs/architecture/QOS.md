# QoS workloads, scheduling and metrics (Phase 3)

Implemented by **harihara1869**. Numerical acceptance tables below are historical controlled cases; use [the fidelity refinement](../research/FIDELITY.md) for current orbital/terminal assumptions. The existing compiled ns-3 backend now supports optional class scheduling, repeatable mixed workloads, live congestion-aware routing and class outcome metrics. Phase 4 has subsequently been implemented; see [the predictive-routing status and contract](PREDICTIVE_ROUTING.md). Prediction and learning are not part of the historical Phase 3 evidence.

## Run it

After the native environment setup in the README:

```bash
.venv/bin/python -m experiments.compare_baselines --case all --seed 7 --output runs/phase3
.venv/bin/python -m experiments.run --scenario scenarios/phase3/burst.json --policy congestion --output runs/burst
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tools.record_phase3_evidence
```

Inside the existing Docker image use `/opt/leo-venv/bin/python` in place of `.venv/bin/python`. The image's `LEO_NS3_PYTHON` selects the ns-3 environment. No Dockerfile or dependency changes were needed. The code is mounted, so rebuilding the image is unnecessary for these source changes.

The comparison runner writes one `scenario.json`, separate `propagation/` and `congestion/` artifacts, and `comparison.json` per case. Each pair uses identical traffic, topology, control times, queue settings and targets. The scenario hash and per-run result/source hashes support reproduction. A failed simulation raises and records failed status; it must not be treated as a completed comparison. This is a small baseline runner, not Phase 7's batch/resume/statistical evaluation system.

## Workloads and service targets

`packet_backend/workloads.py` generates low, normal, burst, hotspot and overload cases. Checked-in seed-7 inputs are in `scenarios/phase3/`. A local seeded generator jitters flow start times; repeating a seed reproduces the workload. These are controlled four-second diamond graphs with a short shared bottleneck and a longer alternate path, not calibrated satellite measurements. Control sends small UDP datagrams, Realtime sends larger paced UDP datagrams, and two Bulk UDP flows expose sharing. Burst cases add finite urgent flows; hotspot adds a concentrated Bulk source; overload increases all base offered rates. Finite TCP Bulk is also supported and tested.

Enable scheduling with `"qos": {}`. Omitting `qos` preserves Phase 2 FIFO. Defaults are:

| Class | Traffic meaning | Experimental target | DRR weight |
| --- | --- | --- | --- |
| CONTROL | Small urgent UDP datagrams | 50 ms end-to-end deadline | 4 |
| REALTIME | Paced UDP, including the STREAMING alias | 100 ms end-to-end deadline | 2 |
| BULK | UDP offered load or finite TCP Linux Reno stream | 20 kbps per active flow; flag backlogged class service gaps over 250 ms | 1 |

These are explicit experiment targets, not standardized SLAs. The deadlines allow several milliseconds of base propagation/serialization and bounded contention in the 1 Mbps fixtures; bursts intentionally challenge them. The Bulk floor is below the nominal class share in these small two-Bulk-flow cases. The 250 ms service-gap threshold is above several nominal 84 ms DRR rounds (1500-byte quantum times total weight 7 at 1 Mbps). None is a universal bound: capacity, packet size, offered demand, failures and number of flows matter. Insufficient offered traffic can also explain a missed throughput target. Completed finite TCP transfers are exempt from the goodput floor.

`qos.weights` supplies all three strictly positive integer weights; `quantum_bytes` defaults to 1500. `qos.targets` allows partial overrides of the fields above. Per-flow `deadline_s` and `min_goodput_bps` override class defaults. `flow_type` is case-insensitive; STREAMING normalizes to REALTIME and an omitted class defaults to BULK. TCP is restricted to Bulk without datagram deadlines; data, ACKs and retransmissions all consume Bulk service.

## Scheduling and routing contract

`packet_backend/qos_queue.h` implements weighted deficit round robin in the existing ns-3 device queue. Credit is measured in **wire bytes**, not packets, and each class remains FIFO. Nonempty classes with positive weights receive service while the link is operational. Transmission is non-preemptive. Empty classes lose unused credit; the scheduler skips them and remains work-conserving over admitted packets.

A link's total waiting-packet budget is reserved across classes: Control gets `floor(N/3)`, Realtime gets `floor(N/3)`, and Bulk gets the remainder. QoS requires at least three slots. Unused reservations are not borrowed. Urgent arrivals cannot fill Bulk's reservation; overload can still drop packets within any class. This protects **class** service, not fairness between individual Bulk flows, and cannot guarantee delivery through failed links. Device flow control remains disabled and there is no second root queue disc.

Both conventional policies use the same destination-based callback and scheduler:

- `propagation`: Dijkstra on current propagation delay.
- `congestion`: Dijkstra on current propagation plus directed queued wire bytes × 8 / capacity. This is a queue-pressure heuristic, not an exact DRR delay prediction; it excludes the packet currently serializing and transport feedback.

Select with `--policy` or pass a registered name/callable to `run()`. The optional `control_interval_s` adds control ticks between topology snapshots, holding the last observed topology. It never interpolates future topology. A topology change and a control tick at the same timestamp produce one update. This lets the congestion baseline respond even on a static graph.

Observations include aggregate and per-class directed waiting packets/bytes and the normalized QoS configuration. No future snapshots, future offered traffic or realised outcomes are passed to the policy. Route validation, link-failure flushing and TTL behavior remain unchanged. Route tables remain destination-based: this phase differentiates service in queues; the Phase 4 contract now supplies optional class-specific routing.

## Metric definitions

QoS runs use result schema **3**; FIFO runs keep schema 2. Phase 3 originally used the private `LEO3` plan; Phase 4 now generates `LEO4`. Regenerate plans through the runner. The common packet accounting remains generated = delivered + dropped + in-flight.

- A deadline is met when delivered delay is at most its deadline (one ns tolerance). Late delivery is distinct from explicit drop and from a packet still in flight whose deadline has expired at the horizon. Pending packets not yet due are censored.
- Deadline success is on-time / (on-time + late + dropped + overdue). Each flow also records on-time / generated as a lower bound when pending outcomes remain. Class totals sum each flow's own deadline outcomes, including overrides.
- Class p95/p99 delay pools **delivered UDP packets**, not per-flow percentiles. Loss and deadline failures must be read alongside these survivor-only tails. TCP is reported by stream bytes/completion, never invented datagram deadlines.
- Existing `goodput_bps` counts delivered application bits over the entire run, including drain/idle time. `active_goodput_bps` counts delivery before the earlier of flow end/horizon, divided by that offered-load window; drain deliveries are excluded. Bulk Jain fairness uses active-window goodput for nonzero-demand Bulk flows. All-zero service gives null rather than a misleading perfect score. Unequal demands/start times make Jain a descriptive statistic, not evidence of equal allocation.
- Bulk starvation intervals are per directed device: time without a Bulk transmission start **while Bulk packets are waiting**. Idle intervals do not count. Service, an empty queue (including failure flush), or the horizon closes a gap. Report the maximum gap and all intervals above the configured threshold. This is scheduler service starvation, not end-to-end availability or per-flow starvation.
- Goodput violations identify flow IDs. Deadline outcomes expose urgent violations even when delivered eventually. The baselines have no target-triggered fallback (`fallback_decisions` is empty with an explanatory note); an unreachable destination receives no route. Targets remain reported under infeasible overload.

Raw `class_queue` and `class_service` events support independent inspection. Event fields are `item=link_id`, `a=direction`, `b=class_id` (Control 0, Realtime 1, Bulk 2); value is waiting packet count or transmitted wire bytes respectively. Live class bytes/counts are retained in `control.json`.

## Acceptance evidence

**35 tests pass natively and in the existing linux/amd64 Docker image, with no skips.** Coverage includes weighted byte sharing with unequal packet sizes, saturated urgent traffic with positive Bulk service, isolated queue limits, directed congestion costs, class observations, deadlines/censoring, known Jain values, idle exclusion, link failure/restoration, TCP Bulk completion and repeatable matched comparisons. The 25 original foundation/packet tests still pass.

All ten seed-7 comparison result hashes match between native execution and Docker. Docker used a Linux host, a mounted workspace, the host UID/GID and disabled network access. Windows/macOS hosts and Apple Silicon emulation were not exercised here.

Evidence: [native test transcript](../evidence/phase3-native-tests.txt), [Docker test transcript](../evidence/phase3-docker-tests.txt), [platform hash checks](../evidence/phase3-platform-check.json), [ten-run metrics and source/result hashes](../evidence/phase3.json). Regenerate with the commands above rather than treating these small fixtures as research conclusions.

| Workload | Policy | Control deadline success | Realtime deadline success | Bulk goodput (kbps, whole run) | Sum of per-flow route changes |
| --- | --- | ---: | ---: | ---: | ---: |
| Low | Propagation / congestion | 100% / 100% | 100% / 100% | 52.8 / 52.8 | 0 / 0 |
| Normal | Propagation / congestion | 100% / 100% | 100% / 100% | 384.0 / 384.0 | 0 / 32 |
| Burst | Propagation / congestion | 43.3% / 74.8% | 34.7% / 44.1% | 259.2 / 259.2 | 0 / 128 |
| Hotspot | Propagation / congestion | 100% / 100% | 100% / 100% | 619.2 / 1293.6 | 0 / 270 |
| Overload | Propagation / congestion | 98.8% / 89.2% | 1.0% / 6.5% | 216.0 / 535.2 | 0 / 272 |

Propagation-only routing keeps concentrating load on the shortest bottleneck even when an alternate path exists. The congestion baseline uses that path but reacts to sampled queues, causing churn even when normal-load delivery needs no improvement. Under overload it improves Realtime/Bulk delivery while **worsening Control deadlines**. Neither policy guarantees urgent service. All ten cases have no Bulk class service gaps above 250 ms, yet hotspot Bulk Jain fairness is only about 0.45: a positive class share does not ensure equal per-flow service.

## Handoff

Remaining implementation is assigned by complete area to `person_1` through `person_4` in [the remaining-work roadmap](../REMAINING_WORK.md). The current-state callback, queue traces, fixed service semantics and matched baseline runner remain the starting point. Keep scheduler/traffic/topology fixed when comparing routing; use held-out seeds and calibrated orbital cases before broader claims.
