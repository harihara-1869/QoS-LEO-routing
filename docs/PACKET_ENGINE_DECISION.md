# Packet engine decision — Phase 1 compatibility exercise

Decision on 23 October 2026: use **modern ns-3 as the authoritative Phase 2 packet engine**, behind a small scenario/topology/results adapter. Keep Python/Skyfield for orbital state and controller orchestration. Do not extend the Python scheduler into a competing full packet engine. This selects an implementation direction; a complete dynamic backend is not yet integrated.

## What was tested

The [official ns-3 Python documentation](https://www.nsnam.org/docs/release/3.44/manual/html/python.html) documents Cppyy bindings and Linux wheels. Installed `ns3==3.44.post0` in `/tmp/leo-ns3-venv` on Python 3.12.3. The optional requirements file pins the binding dependencies too. `tools/probe_ns3.py` loads our small C++ harness through Cppyy; it runs real ns-3 packet events, not a mock.

| Check | Observed result |
| --- | --- |
| Single link: 1000-byte UDP payload, 1 Mbps, 5 ms propagation, transmit at 10 ms | Receive at 23.240 ms, matching 10 + 8.240 + 5 ms (UDP/IP/PPP headers included). |
| 100 packets at 1 ms intervals, two-packet device queue | 15 received, 85 queue drops, queue occupancy observed at one and two packets. |
| Python pauses/reads queue, removes source default route at 30 ms, restores at 60 ms | 100 attempted, 30 send failures, 57 queue drops, 13 received; delivery resumes after restoration. |
| Fixed six-hop route extracted from the baseline at t=1 s | Receive at 98.491499 ms; independent propagation + serialisation calculation gives 98.491498499 ms. |
| Reset between exercises | Four runs complete using `Simulator.Destroy()` between cases. |

[Full numeric evidence](evidence/ns3-probe.json) is checked in. Generated copies are written to `runs/ns3-probe.json`. Assertions fail the command if timing, congestion or feedback checks fail. The source disables flow control and omits root queue discs so the two-packet device queue is the bounded buffer being tested. This is a probe assumption, not a proposed production queueing configuration.

The Python controller calls `Stop`/`Run` on the **same ns-3 clock**, reads a device queue, and changes source routing before resuming. Its route changes affect subsequent unconnected UDP sends. That establishes a usable control boundary; it does not measure PPO training throughput or inference overhead. The historical Python scheduler does not advance packets in parallel.

Cppyy emits `Failed to materialize symbols` diagnostics concerning a time-initialisation helper while loading the C++ headers in this environment. The process nonetheless exits successfully and all independent timing/reset assertions pass. Keep this as a binding/toolchain limitation to investigate before relying on long training runs; a compiled C++ adapter is another option.

## Hypatia result

Fetched the [official repository](https://github.com/snkas/hypatia) at `0ac531c313eba2335f6344b46347140c3a0d4230` and its pinned basic-sim submodule at `3b32597c183e1039be7f0bede17d36d354696776`. Ran its documented optimized build. Its bundled ns-3.31/Waf build stops at configuration because Python 3.12 removed `imp`. OpenMPI's compiler wrapper was also absent; that requirement was not reached. [Failure record](evidence/hypatia-build.txt).

This rules out an unmodified Hypatia build on the current toolchain, not Hypatia in general. A pinned older Linux/Python container remains a future independent reference. Do not run the dependency installation script wholesale against the host.

Source inspection finds `ArbiterSingleForward::SetSingleForwardState` and device `GetQueue()` hooks in Hypatia. Its stock helper loads time-indexed route files; those are not a queue-responsive PPO bridge. A legacy backend would still need controller integration. No Hypatia code was ported. Hypatia documents GPLv2 for ns3-sat-sim and MIT for satgenpy; preserve component attribution if later incorporated.

## Phase 2 boundary and acceptance tests

The current matched case exports one static path from our actual orbital graph and maps link distance to propagation delay. It is not the full 200-satellite topology, not a Hypatia-vs-Skyfield orbital comparison, and not a handover test.

Next implement one ns-3 adapter that translates stable node/link identifiers, capacities, topology updates and workloads, then imports packet outcomes. Validate single link, multi-hop bottleneck, queue overflow and disappearing links before larger scenarios. Choose an explicit in-flight/queued-packet failure policy. Retain a simple Python observation/action boundary at fixed simulated times and measure overhead. Validate TCP Reno independently before any transport claim. Finite terminal budgets and link categories must be agreed before dynamic constellation performance is interpreted.

Reproduction commands are in README.md; the probe stays optional and separate from the lightweight foundation test suite.
