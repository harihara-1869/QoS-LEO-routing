# LENS Empirical Measurement Trace & Simulator Calibration Report

**Author / Owner:** Person 4 (Data / Evaluation)  
**Date:** 12 November 2026  
**Reference Codebase:** APOGEE QoS LEO Routing  
**Calibration Config:** [`calibrations/lens_starlink_v1.json`](../../calibrations/lens_starlink_v1.json)  
**Manifest:** [`data/measurements/lens/manifest.json`](../../data/measurements/lens/manifest.json)  
**Splits:** [`data/measurements/lens/splits.json`](../../data/measurements/lens/splits.json)

---

## 1. Trace Acquisition & Dataset Provenance

To ground our simulation assumptions in genuine Low Earth Orbit operational telemetry, we acquired a 24-hour empirical trace from the **LENS (LEO Satellite Network Measurement Dataset)** project:

- **Source Reference:** Jinwei Zhao and Jianping Pan, *"LENS: A LEO Satellite Network Measurement Dataset"*, ACM MMSys 2024.
- **Repository:** [GitHub clarkzjw/LENS](https://github.com/clarkzjw/LENS) / [Zenodo 10663130](https://zenodo.org/records/10663130).
- **Target Station ID:** `seattle`
- **Location:** Seattle, WA, USA (Starlink User Terminal)
- **Point of Presence (PoP):** Seattle
- **Hardware Generation:** `rev3_proto2` (Standard rectangular dish)
- **Service Tier:** Standard Residential
- **Trace Date:** 2024-01-15 (24 continuous hours, 7,200 probes)
- **Measurement Tool:** IRTT (Isochronous Round Trip Tester)
- **Licensing:** CC BY-SA 4.0 (dataset files), GPL-3.0 (repository code).
- **Raw File Hash (SHA-256):** `5e8f3408d5bb97fccbf82c7b5b78387128801ffcc9d0f4e36cc98f3662d80d28`

---

## 2. Ingestion & Preprocessing Pipeline

### 2.1 High-Precision Timestamps
Documented IRTT logs record timestamps in nanoseconds since the Unix epoch (`~1.705e18` ns for 2024). [`experiments/lens_loader.py`](../../experiments/lens_loader.py) parses and stores these as full 64-bit integers, preventing double-precision floating point mantissa rounding before normalizing to relative episode elapsed seconds.

### 2.2 IRTT Loss Semantics & Zero-Delay Handling
Per the official LENS specification:
- A value of `-1` in `rtt`, `uplink`, or `downlink` indicates packet drop/loss.
- When packet drop occurs unilaterally (e.g., in downlink), the IRTT client reports `0` for the unmeasured return metrics.
- **Strict Preprocessing Rule:** Companion `0` fields and `-1` values are **never** treated as valid `0.0 ms` delay measurements. They are classified into typed drop events (`bilateral`, `uplink_loss`, `downlink_loss`) and excluded from survivor delay quantile calculations.

---

## 3. Chronological Train / Validation / Test Split

To preserve the non-stationary temporal dynamics of satellite orbits, Doppler shifts, and handover cycles, data was partitioned **strictly chronologically** (no random shuffling):

| Split | Time Interval (s) | Sample Count | Share | SHA-256 Digest |
|---|---|---|---|---|
| **Calibration** | $0.0\text{ s} - 51,828.0\text{ s}$ (00:00 - 14:24) | 4,320 | 60% | `31323fa7d07536e9b7da2a7a65d5c50d0546ebe6262bd6469611dee935789a3d` |
| **Validation** | $51,840.0\text{ s} - 69,108.0\text{ s}$ (14:24 - 19:12) | 1,440 | 20% | `5f9a88452347ed3e76a653a7af81dd9bfaa406a1764ea3b5b3ba6d18a8d0d4ee` |
| **Test (Held-Out)** | $69,120.0\text{ s} - 86,388.0\text{ s}$ (19:12 - 24:00) | 1,440 | 20% | `0e4708ba936add952e46cfdc0b5dc046fcb813f568e6482387e38ae8d18408cf` |

---

## 4. Parameter Fitting & Calibration

Observable parameters were fitted on the **Calibration split**:

1. **Ground Link Acquisition Outage (`ground_acquisition_s`):**
   - Empirical handover interruption loss bursts have a median duration of $0.28\text{ s}$.
   - Fitted parameter: **`0.30 s`** (quantized to the simulator's 100 ms physical topology grid).
2. **Access-Layer Latency Baseline:**
   - Minimum RTT observed: $36.99\text{ ms}$ (representing geometric propagation floor + minimum hardware serialization).
   - Median RTT: $46.30\text{ ms}$.
   - Access queue & jitter standard deviation: $5.07\text{ ms}$.
   - 95th percentile RTT: $54.40\text{ ms}$.
   - 99th percentile RTT: $58.95\text{ ms}$.
3. **Empirical Loss Rates:**
   - Total probe drop rate: $2.71\%$
   - Uplink loss rate: $1.39\%$
   - Downlink loss rate: $2.71\%$
   - Directional latency ratio: Uplink accounts for $45.97\%$ of total RTT, Downlink $54.03\%$.

---

## 5. Held-Out Validation

The calibration configuration was evaluated against the held-out **Validation split** (1,440 unseen probes):

| Metric | Calibration Fitted | Validation Observed | Absolute Error | Acceptance Threshold |
|---|---|---|---|---|
| **Median RTT** | $46.298\text{ ms}$ | $47.270\text{ ms}$ | **$0.972\text{ ms}$** | $\le 3.0\text{ ms}$ (PASS) |
| **p95 RTT** | $54.404\text{ ms}$ | $55.866\text{ ms}$ | **$1.462\text{ ms}$** | $\le 5.0\text{ ms}$ (PASS) |
| **p99 RTT** | $58.949\text{ ms}$ | $60.901\text{ ms}$ | **$1.952\text{ ms}$** | $\le 5.0\text{ ms}$ (PASS) |
| **Loss Rate** | $2.708\%$ | $2.847\%$ | **$0.139\%$** | $\le 2.5\%$ (PASS) |

**Validation Gate Status:** **PASSED** (all errors well within bounds).

---

## 6. Architectural Boundary & Limitations

1. **Endpoint Observability Constraint:** Endpoint RTT measurements validate user-to-PoP round-trip delay and access-link acquisition interruptions. They do **not** reveal the internal queuing states of individual space-borne ISL routers or proprietary Starlink ground-station routing algorithms.
2. **Environmental Conditions:** The trace reflects operational conditions of a mid-latitude user terminal (Seattle) during clear-sky / standard weather conditions without heavy rain fade.
