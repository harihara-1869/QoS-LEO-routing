# Phase 1 foundation status

Implementation and validation: 23 October 2026, Linux x86_64, Python 3.12.3.

## Implemented

- One configurable saved scenario, a fixed orbital epoch, deterministic event ordering and repeatable JSON route/topology records.
- Correct flow start/state handling, all generated packets injected, zero-rate support, fractional packet credit, clipped flow boundaries and final partial run intervals.
- Scheduler retains events beyond a run horizon, resumes correctly, orders ties by insertion and rejects past/non-finite times.
- One topology implementation used by the modular pipeline and both viewer entry points. Headless operation does not import OpenGL.
- Fixed plane grouping precision, stable name-based link ordering, degenerate occlusion checks, finite position checks, same-plane range checks and the reversed IOL vector.
- Local constellation loading never attempts implicit downloads or refreshes old synthetic files. Generated epochs are explicit. Invalid counts and non-divisible constellation sizes are rejected.
- Corrected dependencies, documented commands and regression tests. Historical CSVs and pickle remain untouched.
- Immediate route calculation no longer increments packet delivery counters. Output explicitly identifies the route-feasibility baseline.

## Baseline assumptions

Distances are km; event time is seconds relative to a timezone-aware epoch. Skyfield propagates OMM elements with SGP4. Nodes are identified by unique satellite/station names; snapshots persist node ordering. No random traffic is present yet, although the scenario seed is recorded.

Same-plane links form a neighbour ring, gated by range and spherical Earth clearance. Adjacent planes use one pairing offset per plane pair, so a satellite holds at most one cross-plane link into each adjacent plane and every such link is reciprocal; the two seam planes carry one instead of two. This replaced an earlier independent nearest-neighbour choice that produced three to six neighbours per satellite. The rule is a fixed terminal budget, not a finite optical-terminal model: acquisition, tracking and pointing budgets remain unestablished.

Ground access is gated by Skyfield's WGS84 elevation; a second mean-radius sphere check is deliberately omitted because it falsely blocks polar WGS84 ground positions. Each station tracks a bounded number of satellites (`ground_links_per_station`, default one) instead of every satellite above the mask. Satellite occlusion uses a 6371 km sphere. Link rates are differentiated by class: `isl_capacity_bps` for inter-satellite links and `ground_capacity_bps` for ground access. The old unconstrained cone-based IOL model is opt-in (`enable_iol`), disabled in the baseline. Enabling it does not establish physical optical feasibility.

Flow generation at the end of an interval represents bytes earned in that interval; packet creation times are quantised to update boundaries. A trailing incomplete packet is retained as credit, not emitted oversized. This is Phase 1 workload accounting, not a packet-level arrival model. Network and transport outcomes will be owned by ns-3.

## Validation and limits

Run `python -m unittest discover -s tests -v` in the project virtual environment. Tests cover rate conservation, zero rates, interval boundaries, scheduler ordering/resume, occlusion/degenerate geometry, plane grouping, range/visibility gating, topology deltas, route accounting and identical repeated baseline results.

The saved baseline produces 10 packets / 15000 bytes, ten reachable routes and six topology snapshots. Exact hashes are in run manifests. The optional packet-engine probe validates a route extracted from this baseline against independently calculated delay; it does not validate SGP4 against a second orbital implementation.

Interactive OpenGL display was not exercised. The viewer still uses live time and default settings rather than recorded-scenario replay (Phase 8). Raw trace ingestion/calibration, full external orbital cross-validation, physical terminal budgets and transport validation remain explicit follow-ups. The core Phase 1 reproducible-scenario gate is met; research preparation remains ongoing in RESEARCH_GAPS.md and MEASUREMENT_PREPARATION.md.
