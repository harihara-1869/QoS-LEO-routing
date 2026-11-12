"""Simulator calibration engine using empirical LENS measurement splits.

Adheres strictly to the architectural boundary:
- Calibrates observable access-layer parameters (ground acquisition delay,
  channel access jitter, tail quantiles, empirical packet drop rate).
- Does NOT infer unidentifiable internal satellite ISL queues or operator
  internal routing from endpoint RTT alone.
- Validates fitted parameters against the held-out validation set.
- Exports frozen, versioned calibration configuration `calibrations/lens_starlink_v1.json`.
"""

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Dict, Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.lens_loader import LensLoader, compute_statistics


def fit_calibration_parameters(calibration_csv: Path) -> Dict[str, Any]:
    """Fit observable simulator parameters from the calibration split."""
    loader = LensLoader(calibration_csv)
    samples = loader.load()
    stats = compute_statistics(samples)

    rtt_stats = stats["rtt_ms"]
    jitter_stats = stats["jitter_ms"]

    # 1. Ground link acquisition outage estimation:
    # Based on duration of consecutive packet loss bursts during handovers
    loss_durations = []
    cur_start = None
    for s in samples:
        if s.is_loss:
            if cur_start is None:
                cur_start = s.time_s
        else:
            if cur_start is not None:
                duration = s.time_s - cur_start
                if duration > 0:
                    loss_durations.append(duration)
                cur_start = None

    # Quantize to 100 ms simulator physical grid per FIDELITY.md
    if loss_durations:
        median_loss_gap = sorted(loss_durations)[len(loss_durations) // 2]
        # Bounded ground acquisition between 100 ms and 300 ms
        fitted_ground_acq_s = max(0.10, min(0.30, round(median_loss_gap, 2)))
    else:
        fitted_ground_acq_s = 0.15

    # 2. Access latency / queue jitter parameters
    min_rtt = rtt_stats["min_ms"]
    median_rtt = rtt_stats["median_ms"]
    p95_rtt = rtt_stats["p95_ms"]
    p99_rtt = rtt_stats["p99_ms"]
    stddev_rtt = rtt_stats["stddev_ms"]

    # End-to-end access queuing / processing overhead over vacuum propagation
    access_queue_offset_ms = max(0.0, median_rtt - min_rtt)

    # Directional asymmetry: average uplink / RTT ratio
    valid_directional = [
        s.uplink_ms / s.rtt_ms
        for s in samples
        if not s.is_loss and s.rtt_ms and s.uplink_ms and s.rtt_ms > 0
    ]
    uplink_ratio = (
        sum(valid_directional) / len(valid_directional) if valid_directional else 0.46
    )

    fitted_parameters = {
        "version": "1.0.0",
        "calibration_name": "LENS Starlink Seattle rev3_proto2 (2024-01-15)",
        "source_split": calibration_csv.name,
        "source_sha256": hashlib.sha256(calibration_csv.read_bytes()).hexdigest(),
        "sample_count": len(samples),
        "observable_parameters": {
            "ground_acquisition_s": fitted_ground_acq_s,
            "ground_hysteresis_deg": 0.5,
            "ground_min_dwell_s": 0.5,
            "access_base_rtt_ms": round(min_rtt, 3),
            "access_median_rtt_ms": round(median_rtt, 3),
            "access_queue_offset_ms": round(access_queue_offset_ms, 3),
            "access_jitter_stddev_ms": round(stddev_rtt, 3),
            "access_p95_rtt_ms": round(p95_rtt, 3),
            "access_p99_rtt_ms": round(p99_rtt, 3),
            "empirical_loss_rate_pct": round(stats["loss_rate_pct"], 3),
            "uplink_ratio": round(uplink_ratio, 4),
            "downlink_ratio": round(1.0 - uplink_ratio, 4),
        },
        "simulation_overrides": {
            "links": {
                "ground_acquisition_s": fitted_ground_acq_s,
                "ground_hysteresis_deg": 0.5,
                "ground_min_dwell_s": 0.5,
            }
        },
        "architectural_limits": [
            "Calibration fits observable endpoint delay, loss, and handover gaps only.",
            "Internal satellite-to-satellite ISL queues and dynamic routing hops cannot be observed from endpoint RTT.",
            "Assumes clear-sky standard conditions at Seattle ground terminal.",
        ],
    }

    return fitted_parameters


def validate_calibration(
    fitted_params: Dict[str, Any], validation_csv: Path
) -> Dict[str, Any]:
    """Evaluate fitted calibration against held-out validation dataset."""
    loader = LensLoader(validation_csv)
    samples = loader.load()
    val_stats = compute_statistics(samples)

    params = fitted_params["observable_parameters"]
    val_rtt = val_stats["rtt_ms"]

    median_err = abs(params["access_median_rtt_ms"] - val_rtt["median_ms"])
    p95_err = abs(params["access_p95_rtt_ms"] - val_rtt["p95_ms"])
    p99_err = abs(params["access_p99_rtt_ms"] - val_rtt["p99_ms"])
    loss_err = abs(params["empirical_loss_rate_pct"] - val_stats["loss_rate_pct"])

    validation_report = {
        "validation_file": validation_csv.name,
        "validation_sha256": hashlib.sha256(validation_csv.read_bytes()).hexdigest(),
        "sample_count": len(samples),
        "held_out_errors": {
            "median_rtt_error_ms": round(median_err, 3),
            "p95_rtt_error_ms": round(p95_err, 3),
            "p99_rtt_error_ms": round(p99_err, 3),
            "loss_rate_error_pct": round(loss_err, 3),
        },
        "validation_passed": median_err <= 3.0 and p95_err <= 5.0 and loss_err <= 2.5,
    }

    return validation_report


def export_calibration(
    calibration_csv: Path, validation_csv: Path, output_file: Path
) -> Dict[str, Any]:
    """Fit, validate, and export versioned calibration file."""
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fitted = fit_calibration_parameters(calibration_csv)
    val_report = validate_calibration(fitted, validation_csv)

    calibration_artifact = {
        **fitted,
        "validation_report": val_report,
    }

    raw_json = json.dumps(calibration_artifact, indent=2) + "\n"
    output_file.write_text(raw_json)

    digest = hashlib.sha256(raw_json.encode()).hexdigest()
    calibration_artifact["calibration_sha256"] = digest

    # Update with final sha256
    output_file.write_text(json.dumps(calibration_artifact, indent=2) + "\n")
    return calibration_artifact


if __name__ == "__main__":
    cal_path = REPO_ROOT / "data/measurements/lens/calibration.csv"
    val_path = REPO_ROOT / "data/measurements/lens/validation.csv"
    out_path = REPO_ROOT / "calibrations/lens_starlink_v1.json"

    result = export_calibration(cal_path, val_path, out_path)
    print(f"Calibration exported to {out_path.name}:")
    print(f"  Fitted ground acquisition : {result['observable_parameters']['ground_acquisition_s']} s")
    print(f"  Empirical Median RTT      : {result['observable_parameters']['access_median_rtt_ms']} ms")
    print(f"  Empirical p95 RTT         : {result['observable_parameters']['access_p95_rtt_ms']} ms")
    print(f"  Empirical Loss Rate       : {result['observable_parameters']['empirical_loss_rate_pct']} %")
    print(f"  Validation Status         : {'PASSED' if result['validation_report']['validation_passed'] else 'FLAGGED'}")
    print(f"  Median Held-Out Error     : {result['validation_report']['held_out_errors']['median_rtt_error_ms']} ms")
