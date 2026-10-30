# Phase 2 implementation and validation

Implemented and exercised on 30 October 2026 with Python 3.12, GCC 13 and ns-3 3.44.post0 on Linux x86_64. Owner: harihara1869.

## Delivered

- A compiled ns-3 adapter, launched by `run_packet_scenario.py`, integrates the existing orbital topology and configurable workloads.
- Actual hop forwarding, per-direction capacity/serialization, propagation, bounded FIFO queues, queue-overflow drops and packet/stream delivery timing.
- Time-indexed topology changes with queue flush, in-flight invalidation, route withdrawal/recomputation and recovery after restoration. Stable node/source identities allow TCP to survive egress changes.
- Live Python queue observations and route actions on the ns-3 clock, cyclic-action rejection and IPv4 TTL termination.
- UDP terminal accounting, TCP byte/retransmission accounting, delay/goodput, time-weighted queue occupancy, route changes, raw traces and reproducibility manifests.
- Controlled scenarios, independent timing calculations, Reno arithmetic/flow checks and a repeatable orbital-transition example.

The compiled path removes the Cppyy runtime used in the Phase 1 probe; tested runs have empty `engine.stderr`. The old probe and its historical decision record remain available. The Phase 1 runner still performs route-feasibility analysis; the new runner is the packet-simulation entry point.

## Acceptance evidence

The full foundation/backend suite passes **25 tests**, with no skipped packet tests in this environment:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tools.record_phase2_evidence
```

[Recorded summary](evidence/phase2-summary.json) includes input paths, result/source hashes and per-case measurements. [Test transcript](evidence/phase2-tests.txt) records the acceptance run. The evidence command regenerates complete example artifacts under `runs/phase2-evidence/`.

| Case | Independent expectation / observed behavior |
| --- | --- |
| Single link | A 1000-byte UDP payload produces 1030 on-wire bytes. At 1 Mbps with 5 ms propagation, latency is 13.240 ms; sent at 10 ms, received at 23.240 ms. |
| Two-hop path | Two serialization intervals plus 5 + 3 ms propagation produce 24.480 ms latency; the actual hop path is recorded. |
| Bottleneck | Three datagrams traversing an 8 Mbps link then a 1 Mbps link arrive spaced by the slower link's 8.240 ms serialization interval, with increasing queue delay. |
| Queue overflow | 100 offered UDP packets: 15 delivered, 85 explicit overflow drops, none unaccounted for; maximum waiting occupancy is two packets. |
| Disappearance/restoration | Failure at 13 ms drops one transmission and two waiting packets; five sends are unreachable. Restoration at 18 ms enables new delivery without reviving the invalidated transmission. |
| Alternate route | A diamond graph switches from a→b→d to a→c→d after link removal; all three offered packets deliver and one route change is recorded. |
| Live controller | Python observes nonzero queue occupancy, withdraws routes and restores them during the run; 30 sends are labelled unreachable during the withdrawal. |
| End conditions | Tests distinguish unreachable drops from pending packets at the horizon, reject cyclic actions, and record TTL exhaustion. Repeated runs produce identical results. |
| Orbital transitions | 200 satellites, 120 simulated seconds, 31 link transitions and one flow-route change; 200/200 packets delivered. Mean delivery delay is about 46.872 ms. |

## TCP Reno validation and scope

The actual configured algorithm is **`ns3::TcpLinuxReno`**, with SACK disabled. A direct model check exercises slow start (10000→11000 bytes for one segment ACK), loss threshold (10000→5000 bytes), and congestion avoidance (20000→21000 bytes after 20 segment ACKs while window-limited).

A clean 100000-byte transfer delivers all bytes with no retransmissions and completes in 0.859560 s from application start. The two-packet-queue case also delivers all bytes, with 24 retransmitted data segments, observed congestion-window/threshold reductions and completion in 0.927288 s. A dynamic alternate-route case completes the same transfer after a route change, with 11 retransmissions and a 2.124240 s completion delay. These measurements are in the recorded summary and traces.

This validates the selected Reno model's basic arithmetic, end-to-end reliable byte delivery, congestion response and recovery in controlled cases. It does not establish equivalence to every operating-system TCP configuration or validate real Starlink transport behavior. Packet loss events, application delivery and retransmitted wire traffic remain separate measurements.

## Handoff and remaining assumptions

[PACKET_BACKEND.md](PACKET_BACKEND.md) defines inputs, observations/actions, link-failure semantics and result units for Person 2's Phase 3 work. The phase owner can now build class workloads, scheduling, conventional policy comparison and class metrics on this backend. Predictive policies and PPO remain later phases.

Current assumptions are explicit: idealised geometric connectivity, full-duplex point-to-point links, fixed per-link capacity/queue limits, one FIFO class, no root queue discipline, piecewise-constant topology/propagation, and no packet fragmentation. Geometric links do not establish finite optical-terminal feasibility. Snapshot sampling can miss transitions within a step; refine the interval for the experiment. In-progress serialization finishes after invalidation. A packet that changes routes between hops is bounded by TTL. The implementation stores the union of scenario links and detailed event logs, so large-scale runtime/memory behavior remains to be measured in Phase 7.

The orbital geometry has not been independently validated against Hypatia, and no public-measurement calibration has been performed. Those outstanding assumptions remain visible rather than being implied by packet-engine validation.

## Documentation sources

Context7 was used to inspect ns-3 API documentation; installed 3.44 headers, compilation and controlled runs checked the pinned implementation. Relevant primary references: [point-to-point device API](https://www.nsnam.org/docs/release/3.45/doxygen/d7/d99/point-to-point-net-device_8h_source.html), [IPv4 trace signatures](https://www.nsnam.org/docs/release/3.45/doxygen/d9/d0c/ipv4-l3-protocol_8cc_source.html), [Linux Reno implementation](https://www.nsnam.org/docs/release/3.45/doxygen/d5/d28/src_2internet_2model_2tcp-linux-reno_8cc_source.html), and [3.44 device source](https://raw.githubusercontent.com/nsnam/ns-3-dev-git/ns-3.44/src/point-to-point/model/point-to-point-net-device.cc). The newer API pages are supporting documentation, not a claim that the installed version was upgraded.
