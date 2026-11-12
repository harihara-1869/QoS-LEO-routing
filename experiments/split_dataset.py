"""Chronologically split empirical LENS measurement data into Calibration, Validation, and Test sets.

Strict rules enforced:
- Strictly chronological splitting (prevents temporal data leakage and autocorrelation artifacts).
- Frozen split manifests with SHA-256 digests and row counts.
- Exports split CSV files and summary statistics.
"""

import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.lens_loader import LensLoader, compute_statistics


def split_trace(
    input_csv: Path,
    output_dir: Path,
    ratios: tuple[float, float, float] = (0.60, 0.20, 0.20),
) -> Dict[str, Any]:
    """Split input CSV into calibration, validation, and test datasets."""
    assert sum(ratios) == 1.0, "Split ratios must sum to 1.0"
    cal_ratio, val_ratio, test_ratio = ratios
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    loader = LensLoader(input_csv)
    samples = loader.load()
    total_samples = len(samples)

    if total_samples == 0:
        raise ValueError("Cannot split empty measurement trace")

    cal_end_idx = int(total_samples * cal_ratio)
    val_end_idx = int(total_samples * (cal_ratio + val_ratio))

    splits = {
        "calibration": samples[:cal_end_idx],
        "validation": samples[cal_end_idx:val_end_idx],
        "test": samples[val_end_idx:],
    }

    # Read original CSV rows to ensure identical formatting on write
    with open(input_csv, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        header = reader[0]
        data_rows = reader[1:]

    split_manifest = {
        "source_file": input_csv.name,
        "source_sha256": hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        "total_samples": total_samples,
        "split_ratios": {
            "calibration": cal_ratio,
            "validation": val_ratio,
            "test": test_ratio,
        },
        "splits": {},
    }

    indices = {
        "calibration": (0, cal_end_idx),
        "validation": (cal_end_idx, val_end_idx),
        "test": (val_end_idx, total_samples),
    }

    for name, (start_i, end_i) in indices.items():
        out_csv = output_dir / f"{name}.csv"
        sub_rows = data_rows[start_i:end_i]
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(sub_rows)

        out_bytes = out_csv.read_bytes()
        split_sha = hashlib.sha256(out_bytes).hexdigest()
        stats = compute_statistics(splits[name])

        split_manifest["splits"][name] = {
            "filename": out_csv.name,
            "sample_count": len(sub_rows),
            "sha256": split_sha,
            "time_range_s": {
                "start": splits[name][0].time_s,
                "end": splits[name][-1].time_s,
                "duration_s": round(splits[name][-1].time_s - splits[name][0].time_s, 2),
            },
            "statistics": stats,
        }

    manifest_path = output_dir / "splits.json"
    manifest_path.write_text(json.dumps(split_manifest, indent=2))
    return split_manifest


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    input_file = repo_root / "data/measurements/lens/seattle_20240115_irtt.csv"
    manifest = split_trace(input_file, input_file.parent)
    print("Dataset successfully split into calibration, validation, and test sets:")
    for name, info in manifest["splits"].items():
        print(f"  {name:12}: {info['sample_count']} samples, {info['time_range_s']['duration_s']}s duration, SHA: {info['sha256'][:16]}...")
