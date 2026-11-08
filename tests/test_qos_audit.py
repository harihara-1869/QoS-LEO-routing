"""Comprehensive validation unit tests for QoS and deadline audit.

Tests requirements:
1. A packet delivered within deadline counts as on-time.
2. A packet delivered after deadline counts as late.
3. A dropped packet does not count as on-time.
4. Latency threshold boundary condition (delay == deadline).
5. Independent class counters across CONTROL, REALTIME, and BULK.
6. Conversion between seconds, milliseconds, and microseconds.
7. Missing timestamps or deadlines handled safely.
8. Denominators match: generated == delivered + dropped + in_flight.
"""
import unittest
from packet_backend.qos_metrics import deadlines, summarize_qos
from packet_backend.qos import CLASSES


class QosAuditUnitTests(unittest.TestCase):
    def test_packet_delivered_within_deadline_counts_as_on_time(self):
        """Packets delivered with latency strictly below deadline count as on-time."""
        packets = [
            {'packet_id': 1, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.0, 'ended_s': 1.03, 'delay_s': 0.03},
            {'packet_id': 2, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.1, 'ended_s': 1.145, 'delay_s': 0.045},
        ]
        # Deadline 0.05s (50 ms), horizon 2.0s
        res = deadlines(packets, deadline=0.05, horizon=2.0)
        self.assertEqual(res['on_time'], 2)
        self.assertEqual(res['late'], 0)
        self.assertEqual(res['dropped'], 0)
        self.assertEqual(res['resolved'], 2)
        self.assertEqual(res['success_ratio'], 1.0)
        self.assertEqual(res['success_ratio_lower_bound'], 1.0)

    def test_packet_delivered_after_deadline_counts_as_late(self):
        """Packets delivered with latency exceeding deadline count as late, not on-time."""
        packets = [
            {'packet_id': 1, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.0, 'ended_s': 1.055, 'delay_s': 0.055},
            {'packet_id': 2, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.1, 'ended_s': 1.20, 'delay_s': 0.10},
        ]
        res = deadlines(packets, deadline=0.05, horizon=2.0)
        self.assertEqual(res['on_time'], 0)
        self.assertEqual(res['late'], 2)
        self.assertEqual(res['dropped'], 0)
        self.assertEqual(res['resolved'], 2)
        self.assertEqual(res['success_ratio'], 0.0)
        self.assertEqual(res['success_ratio_lower_bound'], 0.0)

    def test_dropped_packet_does_not_count_as_on_time(self):
        """Dropped packets must increment dropped count and never count towards on-time."""
        packets = [
            {'packet_id': 1, 'flow_id': 1, 'status': 'dropped', 'created_s': 1.0, 'ended_s': 1.01, 'delay_s': None},
            {'packet_id': 2, 'flow_id': 1, 'status': 'dropped', 'created_s': 1.1, 'ended_s': 1.12, 'delay_s': None},
            {'packet_id': 3, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.2, 'ended_s': 1.22, 'delay_s': 0.02},
        ]
        res = deadlines(packets, deadline=0.05, horizon=2.0)
        self.assertEqual(res['on_time'], 1)
        self.assertEqual(res['late'], 0)
        self.assertEqual(res['dropped'], 2)
        self.assertEqual(res['resolved'], 3)
        self.assertAlmostEqual(res['success_ratio'], 1.0 / 3.0)
        self.assertAlmostEqual(res['success_ratio_lower_bound'], 1.0 / 3.0)

    def test_latency_threshold_boundary_condition(self):
        """Boundary check: delay == deadline counts as on-time (with 1e-9 precision guard)."""
        deadline = 0.05
        packets = [
            # Exact boundary
            {'packet_id': 1, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.0, 'ended_s': 1.05, 'delay_s': 0.05},
            # Boundary within 1e-9 tolerance
            {'packet_id': 2, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.0, 'ended_s': 1.05 + 1e-10, 'delay_s': 0.05 + 1e-10},
            # Strictly past boundary
            {'packet_id': 3, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.0, 'ended_s': 1.05 + 1e-7, 'delay_s': 0.05 + 1e-7},
        ]
        res = deadlines(packets, deadline=deadline, horizon=2.0)
        self.assertEqual(res['on_time'], 2)
        self.assertEqual(res['late'], 1)
        self.assertEqual(res['dropped'], 0)

    def test_independent_class_counters(self):
        """Counters and latencies for CONTROL, REALTIME, and BULK must remain independent."""
        plan = {
            'duration_s': 2.0,
            'qos': {
                'targets': {
                    'CONTROL': {'deadline_s': 0.05},
                    'REALTIME': {'deadline_s': 0.10},
                    'BULK': {'min_goodput_bps': 10000, 'starvation_s': 0.25},
                }
            },
            'flows': [
                {'id': 1, 'flow_type': 'CONTROL', 'protocol': 'udp', 'start': 0.0, 'end': 2.0, 'rate': 1000, 'deadline_s': 0.05, 'min_goodput_bps': None},
                {'id': 2, 'flow_type': 'REALTIME', 'protocol': 'udp', 'start': 0.0, 'end': 2.0, 'rate': 2000, 'deadline_s': 0.10, 'min_goodput_bps': None},
                {'id': 3, 'flow_type': 'BULK', 'protocol': 'udp', 'start': 0.0, 'end': 2.0, 'rate': 5000, 'deadline_s': None, 'min_goodput_bps': 10000},
            ],
        }
        result = {
            'flows': [
                {'flow_id': 1, 'delivered_bytes': 200, 'goodput_bps': 800.0},
                {'flow_id': 2, 'delivered_bytes': 800, 'goodput_bps': 3200.0},
                {'flow_id': 3, 'delivered_bytes': 2000, 'goodput_bps': 8000.0},
            ],
            'udp_packets': [
                # CONTROL: 2 on-time (delay 0.02s, 0.04s), 1 dropped
                {'packet_id': 1, 'flow_id': 1, 'status': 'delivered', 'created_s': 0.1, 'ended_s': 0.12, 'delay_s': 0.02, 'size_bytes': 100},
                {'packet_id': 2, 'flow_id': 1, 'status': 'delivered', 'created_s': 0.2, 'ended_s': 0.24, 'delay_s': 0.04, 'size_bytes': 100},
                {'packet_id': 3, 'flow_id': 1, 'status': 'dropped', 'created_s': 0.3, 'ended_s': 0.31, 'delay_s': None, 'size_bytes': 100},

                # REALTIME: 1 on-time (0.08s <= 0.10s), 1 late (0.12s > 0.10s)
                {'packet_id': 4, 'flow_id': 2, 'status': 'delivered', 'created_s': 0.1, 'ended_s': 0.18, 'delay_s': 0.08, 'size_bytes': 400},
                {'packet_id': 5, 'flow_id': 2, 'status': 'delivered', 'created_s': 0.2, 'ended_s': 0.32, 'delay_s': 0.12, 'size_bytes': 400},

                # BULK: 2 delivered (no deadline)
                {'packet_id': 6, 'flow_id': 3, 'status': 'delivered', 'created_s': 0.1, 'ended_s': 0.35, 'delay_s': 0.25, 'size_bytes': 1000},
                {'packet_id': 7, 'flow_id': 3, 'status': 'delivered', 'created_s': 0.2, 'ended_s': 0.45, 'delay_s': 0.25, 'size_bytes': 1000},
            ],
            'events': [],
        }

        qos_summary = summarize_qos(plan, result)
        classes = qos_summary['classes']

        # CONTROL verification
        ctrl = classes['CONTROL']
        self.assertEqual(ctrl['udp_generated'], 3)
        self.assertEqual(ctrl['udp_delivered'], 2)
        self.assertEqual(ctrl['udp_dropped'], 1)
        self.assertEqual(ctrl['on_time_count'], 2)
        self.assertEqual(ctrl['late_count'], 0)
        self.assertAlmostEqual(ctrl['deadline_success_rate_pct'], 2.0 / 3.0 * 100.0)
        self.assertAlmostEqual(ctrl['on_time_among_delivered_pct'], 100.0)
        self.assertAlmostEqual(ctrl['delay_mean_s'], 0.03)

        # REALTIME verification
        rt = classes['REALTIME']
        self.assertEqual(rt['udp_generated'], 2)
        self.assertEqual(rt['udp_delivered'], 2)
        self.assertEqual(rt['udp_dropped'], 0)
        self.assertEqual(rt['on_time_count'], 1)
        self.assertEqual(rt['late_count'], 1)
        self.assertAlmostEqual(rt['deadline_success_rate_pct'], 50.0)
        self.assertAlmostEqual(rt['on_time_among_delivered_pct'], 50.0)
        self.assertAlmostEqual(rt['delay_mean_s'], 0.10)

        # BULK verification
        bulk = classes['BULK']
        self.assertEqual(bulk['udp_generated'], 2)
        self.assertEqual(bulk['udp_delivered'], 2)
        self.assertIsNone(bulk['configured_deadline_s'])
        self.assertEqual(bulk['on_time_count'], 0)

    def test_conversion_between_seconds_milliseconds_microseconds(self):
        """Verify unit consistency across seconds, ms, and us."""
        delay_us = 45000  # 45,000 microseconds
        delay_ms = delay_us / 1000.0  # 45.0 ms
        delay_s = delay_ms / 1000.0  # 0.045 s

        deadline_ms = 50.0  # 50 ms
        deadline_s = deadline_ms / 1000.0  # 0.05 s

        packet = {'packet_id': 1, 'flow_id': 1, 'status': 'delivered', 'created_s': 1.0, 'ended_s': 1.0 + delay_s, 'delay_s': delay_s}
        res = deadlines([packet], deadline=deadline_s, horizon=2.0)
        self.assertEqual(res['on_time'], 1)
        self.assertEqual(res['late'], 0)

        # Assert scale relationships
        self.assertEqual(delay_s * 1000.0, delay_ms)
        self.assertEqual(delay_s * 1e6, delay_us)

    def test_missing_timestamps_or_deadlines_handled_safely(self):
        """Empty delay list, unconfigured deadlines, or missing fields must not raise exceptions."""
        plan = {
            'duration_s': 1.0,
            'qos': {'targets': {'CONTROL': {'deadline_s': 0.05}, 'REALTIME': {'deadline_s': 0.1}, 'BULK': {'starvation_s': 0.25}}},
            'flows': [],
        }
        result = {
            'flows': [],
            'udp_packets': [],
            'events': [],
        }
        qos_summary = summarize_qos(plan, result)
        for name in CLASSES:
            c = qos_summary['classes'][name]
            self.assertEqual(c['udp_generated'], 0)
            self.assertEqual(c['udp_delivered'], 0)
            self.assertEqual(c['on_time_count'], 0)
            self.assertEqual(c['late_count'], 0)
            self.assertEqual(c['deadline_success_rate_pct'], 0.0)
            self.assertEqual(c['on_time_among_delivered_pct'], 0.0)
            self.assertIsNone(c['delay_mean_s'])
            self.assertIsNone(c['delay_median_s'])
            self.assertIsNone(c['delay_p95_s'])
            self.assertIsNone(c['delay_p99_s'])

    def test_denominators_and_accounting_balance(self):
        """Verify conservation of packets: generated == delivered + dropped + in_flight."""
        packets = [
            {'packet_id': 1, 'flow_id': 1, 'status': 'delivered', 'created_s': 0.1, 'ended_s': 0.13, 'delay_s': 0.03, 'size_bytes': 100},
            {'packet_id': 2, 'flow_id': 1, 'status': 'delivered', 'created_s': 0.2, 'ended_s': 0.28, 'delay_s': 0.08, 'size_bytes': 100},
            {'packet_id': 3, 'flow_id': 1, 'status': 'dropped', 'created_s': 0.3, 'ended_s': 0.31, 'delay_s': None, 'size_bytes': 100},
            {'packet_id': 4, 'flow_id': 1, 'status': 'in_flight', 'created_s': 0.98, 'ended_s': 1.0, 'delay_s': None, 'size_bytes': 100},
        ]
        plan = {
            'duration_s': 1.0,
            'qos': {'targets': {'CONTROL': {'deadline_s': 0.05}, 'REALTIME': {'deadline_s': 0.1}, 'BULK': {'starvation_s': 0.25}}},
            'flows': [{'id': 1, 'flow_type': 'CONTROL', 'protocol': 'udp', 'start': 0.0, 'end': 1.0, 'rate': 1000, 'deadline_s': 0.05, 'min_goodput_bps': None}],
        }
        result = {
            'flows': [{'flow_id': 1, 'delivered_bytes': 200, 'goodput_bps': 1600.0}],
            'udp_packets': packets,
            'events': [],
        }
        qos_summary = summarize_qos(plan, result)
        ctrl = qos_summary['classes']['CONTROL']

        # Conservation check
        self.assertEqual(ctrl['udp_generated'], ctrl['udp_delivered'] + ctrl['udp_dropped'] + ctrl['udp_in_flight'])
        self.assertEqual(ctrl['udp_undelivered'], ctrl['udp_dropped'] + ctrl['udp_in_flight'])
        self.assertEqual(ctrl['udp_generated'], 4)
        self.assertEqual(ctrl['udp_delivered'], 2)
        self.assertEqual(ctrl['udp_dropped'], 1)
        self.assertEqual(ctrl['udp_in_flight'], 1)
        self.assertEqual(ctrl['on_time_count'], 1)
        self.assertEqual(ctrl['late_count'], 1)

        # Denominator checks
        # End-to-end deadline success rate: on_time / generated = 1 / 4 = 25.0%
        self.assertAlmostEqual(ctrl['deadline_success_rate_pct'], 25.0)
        # On-time among delivered: on_time / delivered = 1 / 2 = 50.0%
        self.assertAlmostEqual(ctrl['on_time_among_delivered_pct'], 50.0)
        # Miss rate: (generated - on_time) / generated = 3 / 4 = 75.0%
        self.assertAlmostEqual(ctrl['deadline_miss_rate_pct'], 75.0)

    def test_evaluate_suite_e2e_report_generation(self):
        """Verify compare_all evaluate_suite correctly processes runs, displays tables, and writes comparison_summary.json."""
        import tempfile
        import json
        from pathlib import Path
        from unittest.mock import patch
        from experiments.compare_all import evaluate_suite

        mock_result = {
            'flows': [
                {'flow_id': 1, 'delivered': 100, 'dropped': 10, 'route_changes': 5},
                {'flow_id': 2, 'delivered': 200, 'dropped': 20, 'route_changes': 8},
                {'flow_id': 3, 'delivered': 500, 'dropped': 50, 'route_changes': 2},
            ],
            'qos': {
                'classes': {
                    'CONTROL': {
                        'udp_generated': 120,
                        'udp_delivered': 100,
                        'udp_dropped': 10,
                        'udp_in_flight': 10,
                        'udp_undelivered': 20,
                        'on_time_count': 90,
                        'late_count': 10,
                        'deadline_met': 90,
                        'delivered': 100,
                        'dropped': 10,
                        'generated': 120,
                        'configured_deadline_s': 0.05,
                        'delay_mean_s': 0.035,
                        'delay_median_s': 0.032,
                        'delay_p95_s': 0.048,
                        'delay_p99_s': 0.049,
                        'sample_count': 100,
                        'deadline_success_rate_pct': 75.0,
                        'on_time_among_delivered_pct': 90.0,
                        'deadline_miss_rate_pct': 25.0,
                        'goodput_bps': 80000.0,
                    },
                    'REALTIME': {
                        'udp_generated': 250,
                        'udp_delivered': 200,
                        'udp_dropped': 20,
                        'udp_in_flight': 30,
                        'udp_undelivered': 50,
                        'on_time_count': 160,
                        'late_count': 40,
                        'deadline_met': 160,
                        'delivered': 200,
                        'dropped': 20,
                        'generated': 250,
                        'configured_deadline_s': 0.10,
                        'delay_mean_s': 0.075,
                        'delay_median_s': 0.070,
                        'delay_p95_s': 0.095,
                        'delay_p99_s': 0.099,
                        'sample_count': 200,
                        'deadline_success_rate_pct': 64.0,
                        'on_time_among_delivered_pct': 80.0,
                        'deadline_miss_rate_pct': 36.0,
                        'goodput_bps': 320000.0,
                    },
                    'BULK': {
                        'udp_generated': 600,
                        'udp_delivered': 500,
                        'udp_dropped': 50,
                        'udp_in_flight': 50,
                        'udp_undelivered': 100,
                        'on_time_count': 0,
                        'late_count': 0,
                        'deadline_met': 0,
                        'delivered': 500,
                        'dropped': 50,
                        'generated': 600,
                        'configured_deadline_s': None,
                        'delay_mean_s': 0.150,
                        'delay_median_s': 0.140,
                        'delay_p95_s': 0.220,
                        'delay_p99_s': 0.245,
                        'sample_count': 500,
                        'deadline_success_rate_pct': 0.0,
                        'on_time_among_delivered_pct': 0.0,
                        'deadline_miss_rate_pct': 0.0,
                        'goodput_bps': 5000000.0,
                    },
                }
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scenario_file = temp_path / "scenario.json"
            scenario_file.write_text(json.dumps({"flows": [], "qos": {}}))
            output_dir = temp_path / "out"

            with patch("experiments.compare_all.run", return_value=mock_result):
                evaluate_suite(scenario_file, output_dir)

            summary_json = output_dir / "comparison_summary.json"
            self.assertTrue(summary_json.exists())
            records = json.loads(summary_json.read_text())

            # Check that heuristic policies were evaluated
            self.assertIn("propagation", records)
            prop = records["propagation"]
            self.assertEqual(prop["summary"]["Control On-Time (%)"], "75.0%")
            self.assertEqual(prop["summary"]["Control Deliv On-Time (%)"], "90.0%")
            self.assertEqual(prop["summary"]["Realtime On-Time (%)"], "64.0%")
            self.assertEqual(prop["summary"]["Realtime Deliv On-Time (%)"], "80.0%")
            self.assertEqual(prop["control"]["mean_latency_ms"], 35.0)
            self.assertEqual(prop["realtime"]["median_latency_ms"], 70.0)
            self.assertEqual(prop["bulk"]["goodput_bps"], 5000000.0)
            self.assertEqual(prop["aggregate"]["delivered"], 800)
            self.assertEqual(prop["aggregate"]["dropped"], 80)
            self.assertEqual(prop["aggregate"]["route_churn"], 15)


if __name__ == '__main__':
    unittest.main()
