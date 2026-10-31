# Packet-backend contract (Phases 2–4)

Phase 4 adds class route tables and causal forecasting; see [the Phase 4 contract and reproduction guide](PHASE4_STATUS.md). The private generated plan is now `LEO4`, and class-routing results use schema 4. Legacy two-part route keys remain supported.

Phase 3 extensions are specified in [QoS configuration and metric semantics](PHASE3_STATUS.md). Omitting `qos` preserves FIFO; enabling it selects class queues and result schema 3.

The Python runner prepares topology/workloads, the compiled ns-3 process owns all packet events, and Python returns routing decisions when that process requests an observation. `schedule_core.py` does not advance packets in this mode. The Phase 1 `SimulationManager` is reused only to generate orbital snapshots before the packet run.

## Entry points and modules

- `run_packet_scenario.run(scenario, output, policy=shortest_routes, ns3_python=None, timeout_s=120)` accepts a JSON path or configuration dictionary and returns the parsed result. Each call starts a fresh ns-3 process, providing reset isolation.
- `packet_backend/scenario.py` validates configuration, assigns stable numeric identities and writes `prepared.json` and the private numeric `engine.plan` format.
- `packet_backend/build.py` locates the pinned wheel using its environment's package metadata and compiles/caches the adapter. `engine.cc` links directly against ns-3.44 libraries; the runtime does not import Cppyy.
- `packet_backend/controller.py` receives observations, calls the Python policy, validates actions and supplies routes to the paused engine.
- `packet_backend/results.py` calculates packet/stream outcomes, delay, run-window goodput, queue occupancy and route changes.

`engine.plan` is an internal generated format, not a public alternative to JSON validation. Run the Python entry point rather than feeding arbitrary files to the executable.

## Scenario inputs

Use `schema_version: 1`, a positive `duration_s`, an integer `seed` and `flows`. Either provide the existing orbital settings (`epoch`, `constellation`, `ground_stations`, `links`, `step_s`) or an explicit `topology` with ordered `nodes` and `snapshots`. The saved fixtures show both forms.

Each explicit snapshot supplies `time_s` and the **complete active link set**. The first snapshot is at zero; later times strictly increase below the run duration. Omission of an existing link means that link is down. Each undirected link has `a`, `b`, and either `delay_s` or `distance_km`; distance converts at 299792.458 km/s. Parallel links and self links are rejected. Link identities are sorted endpoint pairs and persist over their union across all snapshots.

`network` defaults:

| Field | Default | Meaning |
| --- | --- | --- |
| `capacity_bps` | 10000000 | Per-direction capacity of each full-duplex point-to-point link. |
| `queue_packets` | 100 | FIFO waiting-packet limit per direction, excluding the packet in transmission. |
| `mtu_bytes` | 9000 | IP MTU; preserves the existing 1500-byte application payload without fragmentation. |
| `ttl` | 32 | IPv4 hop bound, including protection against transient forwarding loops. |

Explicit links can override `capacity_bps` and `queue_packets`; these settings are constant for that physical link during a run. Delay and availability can change at snapshots. Positive propagation delay is required. No physical error/loss model is added beyond topology failure and congestion.

In orbital mode the per-link rates come from the connectivity configuration, not `network.capacity_bps`:

| Field | Default | Meaning |
| --- | ---: | --- |
| `links.isl_capacity_bps` | 100000000 | Per-direction rate of every inter-satellite and optical link. |
| `links.ground_capacity_bps` | 20000000 | Per-direction rate of every ground-access link. |
| `links.ground_links_per_station` | 1 | Satellites a station tracks at once, highest elevation first. |

`network.capacity_bps` stays the default for explicit graphs only. The defaults keep an ISL:ground ratio of 5:1; the absolute rates are far below operational links so that congestion is reachable at a tractable packet count. A scenario that offers well under these rates will not queue at all. `scenarios/phase5/` and `packet_backend/orbital_workloads.py` show a reduced-scale congested set.

Connectivity uses a finite terminal budget: two same-plane links plus at most one link into each adjacent plane, selected by a single pairing offset per plane pair. The two seam planes therefore carry one cross-plane link instead of two. Ground access is bounded per station. Full-duplex point-to-point links remain an idealisation.

UDP flows specify `flow_id`, named `src`/`dst`, `protocol: "udp"`, `start_time`, `end_time`, `packet_size_bytes` and `data_rate_bps`. One datagram is offered at the start and then at the payload-rate interval until the earlier of end/horizon. Zero rate generates no packets. This is packet-timed CBR traffic, replacing Phase 1's interval-end byte accounting. Headers consume additional link capacity. Oversized payloads are rejected instead of silently fragmenting.

TCP flows specify `protocol: "tcp"`, endpoints/times, `packet_size_bytes` (segment/application-write size) and positive `max_bytes`. Omit `data_rate_bps`: TCP is a finite bulk stream controlled by Linux Reno. The sender stops accepting new application bytes at `end_time`; already buffered data can continue until the run horizon. Source loopback identities remain stable when the egress interface changes. SACK is disabled. All network mechanics remain the same across UDP/TCP runs.

## Ordering and failure semantics

The run interval is `[0, duration_s)`. Topology/control events are registered before traffic, so an update at the same timestamp as a send takes effect first. A packet's link serialization consumes on-wire bytes (including headers), and propagation delay is sampled when that hop begins transmission. A delay update does not retroactively move scheduled receptions.

On a down transition, both directions' waiting queues are flushed and labelled `link_down_queued`. All transmissions already serializing or propagating are invalidated; UDP outcomes are marked `link_down_in_flight` at failure time. A transmission token prevents these packets from being delivered even if the link returns before reception. The underlying point-to-point serializer finishes its current work; it is not interrupted or credited back. New traffic uses the new route, or records `no_route` if unreachable. Restoration allows new traffic but never revives invalidated packets.

Waiting packets on links that remain up continue on their selected outgoing link; subsequent hops consult the new tables. The controller rejects cyclic routing tables. Topology changes between hops can still cause transient revisits, bounded by IPv4 TTL and an explicit `ttl_expired` outcome. Queue overflow is `queue_overflow`. Packets still pending at the horizon are `in_flight`, not inferred drops.

## Controller interface

A policy receives a dictionary containing only current information:

- `time_s`, ordered node names and destination IDs used by the configured flows (including TCP reverse paths).
- Active links with stable IDs, numeric endpoint IDs, capacity, queue limit and current propagation delay.
- Directed queue observations: `link_id`, `direction` (0 is a→b, 1 is b→a), waiting packet count and waiting bytes.

It returns `{(source_node_id, destination_node_id): next_hop_node_id}`. The default policy is propagation-weighted Dijkstra with stable tie breaking. Every installed chain must reach its destination over currently available links; unknown endpoints, unavailable links, cycles and dead ends fail the run. Omitting routes is permitted and produces unreachable outcomes. All actions for one observation are applied within one ns-3 event before packet execution resumes.

The callback receives no future snapshots or realised traffic. `control.json` records each observation/action. Phase 3 adds per-class queue observations and scheduling, the congestion policy, and optional control ticks. Phase 4 optionally installs separate destination-based tables for each class and adds current active-demand metadata plus cumulative arrival/service/drop counters. The Phase 4 guide defines the extended action and output formats. The interface establishes live feedback, not PPO throughput guarantees. Wall-time measurements are recorded separately in the manifest and excluded from the deterministic result hash.

## Results and accounting

`results.json` uses `schema_version: 2` and `mode: "packet_simulation"`. `prepared.json` identifies the node/link mapping and topology schedule. The original input scenario is preserved. `manifest.json` stores the result SHA-256, source hashes, Git state, dependency versions, executable hash, policy identifier and wall times. Store custom policy source/configuration alongside the run when supplying a callback.

UDP has one terminal record per generated datagram: ID, flow, payload size, creation/end times, status/reason, actual named hop path and delivery delay when delivered. For every flow: generated = delivered + dropped + in-flight. Mean/p95/p99 delay uses delivered datagrams; delivery ratio includes all generated datagrams. `goodput_bps` uses unique application bytes divided by the **entire run duration**, including idle/drain time. QoS runs add the deadline/class metrics defined in the Phase 3 contract.

TCP is a byte stream: report requested, accepted, delivered, unaccepted and outstanding bytes, completion time, transmitted data segments and retransmission segments. Retransmissions are detected by repeated TCP sequence ranges; the bounded transfers are below sequence-number wrap. ACKs and retransmissions consume network resources but are not additional application deliveries. Incomplete streams are not silently counted as lost application packets. The congestion-window/threshold and receive traces distinguish transport recovery from route changes.

`events.tsv` records queue changes, wire transmissions/drops, IPv4 drops, link/route changes and TCP traces. Raw events are written only to that file: `results.json` omits them so congested runs stay a few megabytes instead of tens. In-process callers still receive the same list in the returned dictionary. Its drop traces are network events and may overlap the application-level terminal record; do not add them to UDP dropped counts. Queue means integrate occupancy over simulated time, including zero occupancy; route-change counts compare each flow's complete routing path across snapshots and exclude initial installation. All snapshots are retained in the control/prepared files.

`status.json` records running, complete or failed. Reusing a run directory overwrites generated artifacts; results/manifest are removed before a new attempt so a failure cannot appear successful through stale files. Each run should use its own directory when keeping experiment history.

## Terminal/timing refinements

See [FIDELITY_UPDATE.md](FIDELITY_UPDATE.md) for the current contract. `orbital_start_s` advances physical propagation from the OMM epoch without resetting orbital phase; `allow_ground_transit` controls gateway forwarding. `record_control_details: false` retains compact scoring/control records while policies still receive complete current observations. Compact records are marked `recording_mode: compact`; queue histories retain per-class bytes and forecasts retain the fields required for scoring, while full counter/rate diagnostics are omitted. Enable detailed recording when those diagnostics are needed.

Topology and control periods remain separate. The orbital predictor replays acquisition and attachment history on the same physical topology grid, independent of future packet results. ISL pairing offsets remain fixed during an episode. Acquisition, dwell, hysteresis and terminal counts are configured under `links`; legacy defaults retain zero acquisition/hysteresis and an initially established network. The refined fixtures select explicit nonzero values.
