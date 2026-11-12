"""Unit tests for chronological splitting and simulator calibration fitting."""

import json
import tempfile
import unittest
from pathlib import Path

from experiments.fetch_lens import generate_bounded_trace
from experiments.lens_loader import LensLoader
from experiments.split_dataset import split_trace
from experiments.calibrate import export_calibration, fit_calibration_parameters, validate_calibration


class CalibrationUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        # Generate small bounded trace for fast testing
        self.trace_csv = self.temp_path / "test_trace.csv"
        generate_bounded_trace(self.trace_csv, seed=123, num_samples=500)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_chronological_split_integrity(self):
        """Verify splits do not overlap, preserve chronological order, and sum correctly."""
        manifest = split_trace(self.trace_csv, self.temp_path, ratios=(0.6, 0.2, 0.2))
        
        self.assertEqual(manifest["total_samples"], 500)
        splits = manifest["splits"]
        self.assertEqual(splits["calibration"]["sample_count"], 300)
        self.assertEqual(splits["validation"]["sample_count"], 100)
        self.assertEqual(splits["test"]["sample_count"], 100)

        # Check chronological ordering: cal_end < val_start < val_end < test_start
        cal_end = splits["calibration"]["time_range_s"]["end"]
        val_start = splits["validation"]["time_range_s"]["start"]
        val_end = splits["validation"]["time_range_s"]["end"]
        test_start = splits["test"]["time_range_s"]["start"]

        self.assertLessEqual(cal_end, val_start)
        self.assertLessEqual(val_end, test_start)

        # Verify CSV files exist on disk
        self.assertTrue((self.temp_path / "calibration.csv").exists())
        self.assertTrue((self.temp_path / "validation.csv").exists())
        self.assertTrue((self.temp_path / "test.csv").exists())

    def test_calibration_fitting_and_validation(self):
        """Verify parameter fitting, bounds, and held-out validation report."""
        split_trace(self.trace_csv, self.temp_path, ratios=(0.6, 0.2, 0.2))
        cal_csv = self.temp_path / "calibration.csv"
        val_csv = self.temp_path / "validation.csv"
        out_json = self.temp_path / "cal_test.json"

        artifact = export_calibration(cal_csv, val_csv, out_json)

        params = artifact["observable_parameters"]
        # Ground acquisition must be bounded realistically
        self.assertGreaterEqual(params["ground_acquisition_s"], 0.10)
        self.assertLessEqual(params["ground_acquisition_s"], 0.35)

        # Latency quantiles must be monotonic: min <= median <= p95 <= p99
        self.assertLessEqual(params["access_base_rtt_ms"], params["access_median_rtt_ms"])
        self.assertLessEqual(params["access_median_rtt_ms"], params["access_p95_rtt_ms"])
        self.assertLessEqual(params["access_p95_rtt_ms"], params["access_p99_rtt_ms"])

        # Check validation report
        val = artifact["validation_report"]
        self.assertTrue(val["validation_passed"])
        self.assertLess(val["held_out_errors"]["median_rtt_error_ms"], 3.0)

        # Check json file was written and can be loaded
        self.assertTrue(out_json.exists())
        loaded = json.loads(out_json.read_text())
        self.assertEqual(loaded["version"], "1.0.0")
        self.assertIn("calibration_sha256", loaded)


if __name__ == "__main__":
    unittest.main()
