"""Unit tests for LENS data loader, timestamp precision, loss semantics, and statistics."""

import csv
import tempfile
import unittest
from pathlib import Path

from experiments.lens_loader import LensLoader, MeasurementSample, compute_statistics


class LensLoaderUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_timestamp_magnitude_detection(self):
        """Verify nanosecond, microsecond, millisecond, and second parsing."""
        # Nanoseconds
        ts_ns = 1705276800000000000
        self.assertEqual(LensLoader.parse_timestamp_ns(str(ts_ns)), ts_ns)

        # Microseconds
        ts_us = 1705276800000000
        self.assertEqual(LensLoader.parse_timestamp_ns(str(ts_us)), ts_us * 1_000)

        # Milliseconds
        ts_ms = 1705276800000
        self.assertEqual(LensLoader.parse_timestamp_ns(str(ts_ms)), ts_ms * 1_000_000)

        # Seconds (float)
        ts_s = 1705276800.5
        self.assertEqual(LensLoader.parse_timestamp_ns(str(ts_s)), 1705276800500000000)

    def test_irtt_loss_semantics_and_zero_handling(self):
        """Strict test: -1 is loss, companion 0s must NEVER be treated as 0 ms latency."""
        csv_file = self.temp_path / "test_irtt.csv"
        rows = [
            ["timestamp", "rtt", "uplink", "downlink"],
            # Normal delivered probe
            ["1705276800000000000", "42.5", "20.1", "22.4"],
            # Bilateral loss (-1 in all fields)
            ["1705276801000000000", "-1", "-1", "-1"],
            # Downlink loss per LENS documentation: -1 in downlink, companion 0s in rtt and uplink
            ["1705276802000000000", "0", "0", "-1"],
            # Uplink loss: -1 in uplink, companion 0s in rtt and downlink
            ["1705276803000000000", "0", "-1", "0"],
            # Normal delivered probe
            ["1705276804000000000", "48.2", "22.0", "26.2"],
        ]
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        loader = LensLoader(csv_file)
        samples = loader.load()
        self.assertEqual(len(samples), 5)

        # Probe 0: normal
        self.assertFalse(samples[0].is_loss)
        self.assertEqual(samples[0].rtt_ms, 42.5)
        self.assertEqual(samples[0].uplink_ms, 20.1)
        self.assertEqual(samples[0].downlink_ms, 22.4)
        self.assertEqual(samples[0].loss_type, "none")

        # Probe 1: bilateral loss
        self.assertTrue(samples[1].is_loss)
        self.assertIsNone(samples[1].rtt_ms)
        self.assertIsNone(samples[1].uplink_ms)
        self.assertIsNone(samples[1].downlink_ms)
        self.assertEqual(samples[1].loss_type, "bilateral")

        # Probe 2: downlink loss - companion 0s MUST NOT be converted to 0.0 ms!
        self.assertTrue(samples[2].is_loss)
        self.assertIsNone(samples[2].rtt_ms)
        self.assertIsNone(samples[2].uplink_ms)
        self.assertIsNone(samples[2].downlink_ms)
        self.assertEqual(samples[2].loss_type, "downlink")

        # Probe 3: uplink loss
        self.assertTrue(samples[3].is_loss)
        self.assertIsNone(samples[3].rtt_ms)
        self.assertIsNone(samples[3].uplink_ms)
        self.assertIsNone(samples[3].downlink_ms)
        self.assertEqual(samples[3].loss_type, "uplink")

        # Probe 4: normal
        self.assertFalse(samples[4].is_loss)
        self.assertEqual(samples[4].rtt_ms, 48.2)

    def test_compute_statistics(self):
        """Verify delivery/loss rates, quantiles, and jitter calculations."""
        samples = [
            MeasurementSample(100, 0.0, 40.0, 18.0, 22.0, False, "none"),
            MeasurementSample(200, 1.0, 45.0, 20.0, 25.0, False, "none"),
            MeasurementSample(300, 2.0, None, None, None, True, "downlink"),
            MeasurementSample(400, 3.0, 50.0, 22.0, 28.0, False, "none"),
            MeasurementSample(500, 4.0, None, None, None, True, "bilateral"),
        ]
        stats = compute_statistics(samples)
        self.assertEqual(stats["total_probes"], 5)
        self.assertEqual(stats["delivered_probes"], 3)
        self.assertEqual(stats["lost_probes"], 2)
        self.assertAlmostEqual(stats["loss_rate_pct"], 40.0)

        # RTT percentiles on delivered probes: [40.0, 45.0, 50.0]
        rtt = stats["rtt_ms"]
        self.assertEqual(rtt["min_ms"], 40.0)
        self.assertEqual(rtt["median_ms"], 45.0)
        self.assertEqual(rtt["max_ms"], 50.0)
        self.assertAlmostEqual(rtt["mean_ms"], 45.0)


if __name__ == "__main__":
    unittest.main()
