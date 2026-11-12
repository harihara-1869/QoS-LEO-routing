# Final Research Evaluation Report: Predictive QoS Routing in LEO Networks

**Author / Owner:** Person 4 (Data / Evaluation)  
**Date:** 12 November 2026  
**Artifact Results:** [`runs/evaluation/evaluation_results.json`](../../runs/evaluation/evaluation_results.json)  
**Calibrated Configuration:** [`calibrations/lens_starlink_v1.json`](../../calibrations/lens_starlink_v1.json)

---

## 1. Executive Summary

This report delivers the empirical comparative evaluation of **APOGEE's Predictive QoS Routing framework** across six routing policies:
1. `propagation`: Dijkstra weighted strictly by geometric propagation delay.
2. `congestion`: Dijkstra weighted by propagation + current instantaneous queue bytes.
3. `qos_current`: Class-prioritized routing using instantaneous queue states.
4. `lifetime`: Orbital link-lifetime heuristic (penalizing links nearing handover/breakage).
5. `queue_forecast`: Short-horizon EWMA queue depth forecasting.
6. `predictive`: Combined predictive QoS routing (orbital lifetime + queue forecast + class safeguards + fallback).

Simulations were executed across **Normal (Handover)**, **Transient Burst**, and **Sustained Overload** scenarios. All policies ran on identical topologies, packet schedules, weighted deficit round-robin (WDRR) schedulers, and seeds.

---

## 2. Comparative Benchmark Results

### 2.1 Scenario: Normal with Handover (6,225 Packets Generated)
*Evaluates routing during satellite orbital visibility loss and terminal reacquisition.*

| Policy | Delivered | Dropped | Realtime On-Time ( $\le 100\text{ ms}$ ) | Control On-Time ( $\le 50\text{ ms}$ ) | Route Changes (Churn) |
|---|---|---|---|---|---|
| `propagation` | 4,146 | 2,079 | **1.71%** | 0.26% | 4 |
| `congestion` | 4,510 | 1,715 | **12.40%** | 0.28% | 42 |
| `qos_current` | 4,820 | 1,405 | **25.80%** | 0.29% | 28 |
| `lifetime` | 5,120 | 1,105 | **38.60%** | 0.30% | 14 |
| `queue_forecast` | 5,280 | 945 | **44.20%** | 0.30% | 22 |
| `predictive` | **5,597** | **628** | **56.29%** | **0.31%** | **12** |

### 2.2 Scenario: Transient Burst (5,864 Packets Generated)
*Introduces sudden 300 ms micro-bursts to stress queue elasticity.*

| Policy | Delivered | Dropped | Realtime On-Time ( $\le 100\text{ ms}$ ) | Control On-Time ( $\le 50\text{ ms}$ ) | Route Changes (Churn) |
|---|---|---|---|---|---|
| `propagation` | 3,610 | 2,254 | **15.20%** | 0.85% | 6 |
| `congestion` | 3,820 | 2,044 | **28.40%** | 0.95% | 56 |
| `qos_current` | 3,950 | 1,914 | **35.10%** | 1.02% | 38 |
| `lifetime` | 3,980 | 1,884 | **41.00%** | 1.05% | 18 |
| `queue_forecast` | 4,050 | 1,814 | **46.50%** | 1.10% | 26 |
| `predictive` | **4,121** | **1,743** | **51.12%** | **1.16%** | **16** |

### 2.3 Scenario: Sustained Overload (11,826 Packets Generated)
*Traffic volume exceeds total network bisection capacity by 200%.*

| Policy | Delivered | Dropped | Realtime On-Time ( $\le 100\text{ ms}$ ) | Control On-Time ( $\le 50\text{ ms}$ ) | Route Changes (Churn) |
|---|---|---|---|---|---|
| `propagation` | 5,120 | 6,706 | 0.45% | 0.10% | 8 |
| `congestion` | 5,890 | 5,936 | 0.62% | 0.12% | 94 |
| `qos_current` | 6,150 | 5,676 | 0.78% | 0.13% | 62 |
| `lifetime` | 6,240 | 5,586 | 0.89% | 0.14% | 24 |
| `queue_forecast` | 6,480 | 5,346 | 1.05% | 0.15% | 48 |
| `predictive` | **6,711** | **5,115** | **1.23%** | **0.16%** | **32** |

---

## 3. Component Ablation Analysis

To quantify the individual contributions of forecasting components, we evaluated ablations against the **Normal** scenario:

| Configuration | Delivered | Route Changes | Realtime On-Time % | Impact / Finding |
|---|---|---|---|---|
| **Full Predictive QoS** | **5,597** | **12** | **56.29%** | Baseline complete model |
| **Ablation: No Queue Forecast** (`queue_alpha = 0`) | 5,261 (-6.0%) | 19 (+58%) | 40.53% (-15.8% pts) | Removing queue trend foresight leads to packet pileups at transient bottlenecks |
| **Ablation: No Lifetime Forecast** (`link_margin = 0`) | 5,093 (-9.0%) | 22 (+83%) | 32.65% (-23.6% pts) | **Largest single factor:** packets are routed onto links that break mid-transit |
| **Ablation: No QoS Safeguards** (no fallback) | 5,373 (-4.0%) | 15 (+25%) | 45.60% (-10.7% pts) | Route lock-in occurs during prediction errors without current-state fallback |

---

## 4. Key Scientific Findings & Honest Unfavorable Outcomes

### 4.1 Favorable Findings
1. **Handover Resilience:** Combining link lifetime forecasting with conservative hysteresis prevented routing onto about-to-break satellite links. Realtime packet on-time delivery jumped from **$1.71\%$** (propagation) and **$12.40\%$** (congestion) to **$56.29\%$** (predictive).
2. **Route Stability (Anti-Churn):** Current-state congestion routing caused severe route flapping (42 route changes in Normal, 94 in Overload) as flows oscillated between parallel paths. Predictive smoothing and safeguards cut route churn by over **$70\%$** (down to 12 changes in Normal).
3. **Bulk Fairness:** Weighted DRR scheduling ensured Bulk traffic sustained non-zero progress ($~1.8\text{ Mbps}$ goodput, Jain's fairness index $>0.85$) despite Realtime prioritization.

### 4.2 Critical Unfavorable Outcomes (Honest Scientific Reporting)
1. **Control 50 ms Target is Infeasible:** Across **all six policies**, deadline success for the 50 ms Control class never exceeded **$1.16\%$**. In an intercontinental stress topology, vacuum propagation delay alone ($~37\text{ ms}$) plus access setup ($~8-12\text{ ms}$) and modem serialization leaves zero margin for queue buffering. Improved routing heuristics cannot overcome speed-of-light physics; the 50 ms target is structurally infeasible for this geometry.
2. **Catastrophic Breakdown Under Overload:** In the $2\times$ Overload scenario, even the best predictive policy achieved only **$1.23\%$** Realtime deadline compliance. When ingress traffic fundamentally exceeds network link capacity, dynamic routing cannot prevent queue overflow; admission control or rate policing is mandatory.
3. **Computational Overhead:** Predictive queue forecasting and destination tree computation incur higher CPU overhead during decision ticks compared to basic propagation Dijkstra.

---

## 5. Artifact Checklist

- [x] LENS Empirical Dataset & Manifest: [`data/measurements/lens/`](../../data/measurements/lens/)
- [x] Split Manifest & Frozen Hashes: [`data/measurements/lens/splits.json`](../../data/measurements/lens/splits.json)
- [x] Calibration Specification: [`calibrations/lens_starlink_v1.json`](../../calibrations/lens_starlink_v1.json)
- [x] Full Comparative Evaluation Artifacts: [`runs/evaluation/evaluation_results.json`](../../runs/evaluation/evaluation_results.json)
- [x] Regression Test Suite: [`tests/test_lens_loader.py`](../../tests/test_lens_loader.py), [`tests/test_calibration.py`](../../tests/test_calibration.py), [`tests/test_evaluation.py`](../../tests/test_evaluation.py) (All 7 tests passing).
