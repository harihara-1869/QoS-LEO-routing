# Terminal and timing fidelity update — 31 October 2026

This update documents the simulator fidelity improvements and their validation. It extends the user's constrained topology and congested workloads. The model now represents terminal reservations, acquisition outages and attachment stability; the short evaluation episodes actually include a handover and expose their bursts to the controller.

## Current behavior

- `orbital_start_s` advances the physical orbit from the OMM epoch without regenerating/resetting its mean anomaly. The refined fixtures start at 12 seconds. Logical packet time still starts at zero.
- Physical topology is sampled every **100 ms**, separately from **50 ms** routing decisions. The 300 ms urgent bursts have multiple observation/action opportunities. Physical positions are not accelerated.
- Same-plane and cross-plane links reserve a finite number of terminals at both ends. Cross-plane pairing offsets persist through an episode instead of being globally reoptimized at each snapshot. Optional IOL links are included in the same terminal budget; duplicate physical pairs are excluded.
- Ground selection enforces both the station antenna count and the satellite's ground-beam count. Incumbents receive elevation hysteresis and minimum dwell protection, unless visibility is lost. Allocation is deterministic and shared across stations.
- A newly selected link reserves a terminal while acquiring, but cannot carry packets until acquisition completes. Lost/removed links release reservations; restoration must reacquire. The existing packet engine drops waiting/in-progress packets on link removal, so a handover outage has packet-level consequences.
- The independent orbital predictor replays the same terminal lifecycle on the physical topology grid. Cached future model queries cannot mutate earlier forecasts or read future actual packet/topology records. It predicts held topology states between physical update times, matching simulator semantics.
- The refined fixtures disable gateway transit. Gateways may originate/receive traffic but cannot relay between satellites. Conventional routing, predictive routing and custom-action validation all enforce this. Legacy scenarios keep their previous behavior unless explicitly configured.

## Explicit terminal parameters

All parameters below are under `links`. Counts must be positive integers; times/margins must be finite and nonnegative. They are **configurable experimental assumptions**, not measured universal hardware specifications.

| Parameter | Legacy default | Refined fixtures | Meaning |
| --- | ---: | ---: | --- |
| `isl_terminals_per_satellite` | 4 | 4 | Total simultaneous ISL reservations, including acquisition and optional IOL. |
| `ground_links_per_station` | 1 | 2 | Tracking antennas per gateway. |
| `ground_beams_per_satellite` | 4 | 2 | Simultaneous ground-link reservations per satellite across all gateways. |
| `isl_acquisition_s` | 0 | 1.0 | Setup delay for new/re-established ISLs. |
| `ground_acquisition_s` | 0 | 0.15 | Setup delay for new/re-established ground links. |
| `ground_hysteresis_deg` | 0 | 0.5 | Elevation advantage required to replace an incumbent after its dwell interval. |
| `ground_min_dwell_s` | 0 | 0.5 | Minimum incumbent hold interval while still visible. |
| `initial_links_ready` | true | true | Start from an established network. Set false to model cold acquisition at episode start. |

Hysteresis and beam caps select desired reservations before acquisition is applied. The policy is break-before-make per occupied terminal; another ready antenna can still carry traffic during reacquisition. Pending links consume slots, and a selected target can lose visibility before acquisition completes. These dynamics are not a detailed antenna pointing/slew controller.

Acquisition completion and attachment changes are quantized to physical topology updates. A configured 150 ms acquisition can therefore appear as a 200 ms interruption on a 100 ms grid. Reduce `step_s` for a timing convergence check; this increases propagation/recording cost. Control decisions alone do not advance the physical topology.

## Capacity and timing assumptions

The fixtures retain 10 Mbps ISLs and 2 Mbps ground links as a tractable stress configuration. The 5:1 ratio is now explicitly an **assumption**, not a physical calibration claim. Neither changing capacities nor proportionally changing demand preserves serialization time relative to propagation, deadlines, buffer drain, terminal setup and orbit motion.

`experiments.fidelity.scaled_scenario(config, factor, matched_demand=False)` changes capacities with fixed traffic. Setting `matched_demand=True` also scales offered payload rates. It deliberately preserves packet sizes, orbital motion, setup times, deadlines and update intervals. The two modes expose scaling sensitivity rather than asserting equivalence. Packet headers consume capacity in both modes.

The evidence suite includes:

1. Normal traffic with propagation and predictive routing on the same handover episode.
2. Bursts and overload with predictive routing.
3. Doubled capacities with fixed demand.
4. Doubled capacities with doubled demand, leaving other time scales unchanged.

These experiments are bounded sensitivity checks, not calibration, statistically supported policy rankings or complete robustness sweeps. The generator accepts shorter positive durations above one second and places burst windows proportionally so they remain inside those runs.

## Geometry validation

`tests/data/vallado_00005.json` records four published Vallado SGP4 verification vectors at 0, 360, 720 and 1080 minutes, with TLE input, position in km and velocity in km/s in TEME. These were transcribed from `SGP4-VER.TLE` / `tcppver.out` shipped with pinned `sgp4==2.25`. Source: [Vallado et al., Revisiting Spacetrack Report #3](https://celestrak.org/publications/AIAA/2006-6753/).

Tests propagate through Skyfield and transform back to the matching TEME frame, checking **position and velocity components**, with tolerances of 1 m and 1 mm/s. Observed maximum component errors were approximately 0.087 m and 0.104 mm/s; epoch conversion and frame round-off are included. This is substantially stronger algorithm/pipeline validation than only bounding changes in a scalar two-body position error. It is still not a validation against measured spacecraft trajectories or a different physical force model.

Simulation time now uses split Julian dates to preserve fractional-second precision. Ground elevation reuses already propagated satellite and station positions; the existing independent ENU tests validate the equivalent coordinate calculation.

## Recording and resource cost

Fine control intervals produce much larger histories than the previous one-second cases. `record_control_details: false` enables compact retained histories in the refined fixtures. Live policies still receive full observations and counters. Compact records are marked `recording_mode: compact`; they retain current per-class queue bytes, class routes, active demands, forecast samples and scoring fields, while omitting redundant counter/rate diagnostics and link metadata. Full traces are available with `record_control_details: true` and raw packet/network events remain in TSV files.

Compact mode reduces duplication; it is not a streaming simulator. Memory/runtime still grow with packet count, route history and decision count. The old five-second/one-second-control memory figures in the Phase 5 handoff are historical. Start with the quick command below before scheduling many concurrent environments or long training runs.

## Validation and reproduction

Tests cover acquisition/reacquisition, monotonic state, minimum dwell and hysteresis, satellite ground-beam sharing, ISL/IOL caps, gateway transit restrictions, observed bursts, actual attachment changes, independent forecast replay, rate sensitivity semantics and the published orbital vectors, alongside the original tests.

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m experiments.fidelity --quick
.venv/bin/python -m experiments.fidelity --evidence runs/fidelity/evidence.json
```

Inside the existing Docker image, use `python` or `/opt/leo-venv/bin/python`. No dependency or image changes are required. Evidence and platform verification are recorded below after the validation suite completes.

## Remaining limits

Actual optical/RF link budgets, rain/interference/pointing-error distributions, hardware-specific terminal steering and measured traffic are not supplied by this repository. Acquisition and hysteresis values therefore remain parameters to calibrate, not physical constants. Per-link rates are fixed rather than computed from power, modulation/coding, antenna gain and weather. Satellite resource caps bound aggregate possible ground throughput by beam count × link rate, but do not model a shared physical modem/spectrum scheduler.

Routing updates remain centralized and instantaneous at each control tick; Python decision wall time does not add simulated delay. Distributed/stale telemetry and control-plane signaling are not modeled.

Orbital availability forecasts still share the simulator's physical model. The reference-vector tests verify the implementation, while held-out measured trajectories and link telemetry are needed to quantify forecast uncertainty in practice. Phase 6 calibration remains necessary for claims about a real operator's absolute latency, throughput or loss. Phase 5 learned routing has not been implemented by this update.

## Recorded results

**At the 31 October refinement checkpoint, 86 tests passed without skips natively and in Docker.** The normal predictive run's entire evidence record and result hash match between environments. This container verification used a Linux host; Windows/macOS hosts and Apple Silicon emulation were not exercised.

Each refined five-second run includes an old-link removal at **3.9 s** and replacement activation at **4.1 s**, exposing the quantized acquisition interruption. All four added burst flows appear at **five controller observation ticks each**, versus zero previously. No delivered packet in the six recorded runs traverses an intermediate gateway with transit disabled.

| Experiment | Generated | Delivered | Dropped | Control on-time | Realtime on-time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal, propagation | 6,225 | 4,146 | 2,079 | 0.26% | 1.71% |
| Normal, predictive | 6,225 | 5,597 | 628 | 0.31% | 56.29% |
| Burst, predictive | 5,864 | 4,121 | 1,743 | 1.16% | 51.12% |
| Overload, predictive | 11,826 | 6,711 | 5,115 | 0.16% | 1.23% |
| Double capacity, fixed demand, propagation | 6,225 | 6,151 | 74 | 5.63% | 100% |
| Double capacity and demand, propagation | 12,448 | 8,218 | 4,230 | 2.59% | 20.96% |

No datagrams remain in flight in these recorded runs. These are individual seeded observations, not confidence intervals. In particular, the 50 ms Control target is almost never met in the chosen intercontinental stress configuration. Improved model fidelity does not imply feasible QoS requirements or a successful routing policy. Do not use total deliveries alone to claim QoS success, and do not silently relax targets to improve results.

The rate-scaling sensitivity is visible even when demand/capacity is kept proportional: normal propagation Realtime deadline success changes from 1.71% to 20.96%, and delivered Bulk p95 delay changes from about 360 ms to 207 ms. Thus a preserved rate ratio is insufficient for physical timing similarity. Match real capacities/demand, packetization and service targets through calibration before interpreting absolute metrics as operator predictions.

Evidence: [six-run results with source/result hashes](../evidence/fidelity.json), [native test transcript](../evidence/fidelity-native-tests.txt), [Docker transcript](../evidence/fidelity-docker-tests.txt), [platform verification](../evidence/fidelity-platform.json). Full histories/manifests remain under `runs/fidelity/evaluation/`; each run's output includes the exact scenario. Earlier measurements in the Phase 5 handoff are historical.
