"""Congested orbital scenarios and the reduced-scale capacity regime."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from packet_backend.build import ROOT
from packet_backend.orbital_workloads import CASES, orbital_workload
from run_packet_scenario import run

HAVE_ENGINE = bool(shutil.which('g++')) and Path(
    os.environ.get('LEO_NS3_PYTHON', str(ROOT / '.venv-ns3/bin/python'))).exists()


class OrbitalWorkloadTests(unittest.TestCase):
    def test_fixtures_match_the_generator(self):
        for case in CASES:
            with self.subTest(case=case):
                saved = json.loads((ROOT / 'scenarios/phase5' / f'{case}.json').read_text())
                self.assertEqual(orbital_workload(case), saved)

    def test_generator_is_seed_deterministic(self):
        self.assertEqual(orbital_workload('burst', 7), orbital_workload('burst', 7))
        self.assertNotEqual(orbital_workload('burst', 7), orbital_workload('burst', 8))

    def test_design_places_congestion_at_ground_access(self):
        """At least one station is offered its whole aggregate ground capacity."""
        for case in CASES:
            config = orbital_workload(case)
            capacity = config['links']['ground_capacity_bps'] * config['links']['ground_links_per_station']
            offered = {}
            for flow in config['flows']:
                offered[flow['src']] = offered.get(flow['src'], 0) + flow['data_rate_bps']
            self.assertTrue(offered)
            self.assertGreaterEqual(max(offered.values()), capacity, f'{case}: no station saturates')
            # The bottleneck is ground access, not the inter-satellite mesh.
            self.assertGreater(config['links']['isl_capacity_bps'],
                               config['links']['ground_capacity_bps'])

    def test_offered_load_stays_below_isl_capacity_in_aggregate(self):
        """Congestion is placed at ground access, not by overloading every ISL."""
        for case in CASES:
            config = orbital_workload(case)
            total = sum(flow['data_rate_bps'] for flow in config['flows'])
            self.assertLess(total, config['links']['isl_capacity_bps'] * len(config['ground_stations']))

    def test_rejects_invalid_requests(self):
        with self.assertRaises(ValueError):
            orbital_workload('unknown-case')
        with self.assertRaises(ValueError):
            orbital_workload('normal', duration=0.5)

    def test_scenario_uses_the_class_routing_interface(self):
        config = orbital_workload('normal')
        self.assertIn('qos', config)
        self.assertIn('prediction', config)
        self.assertLessEqual(config['prediction']['orbital_horizon_s'], config['duration_s'])
        self.assertEqual(config['links']['ground_links_per_station'], 2)


@unittest.skipUnless(HAVE_ENGINE, 'Install the pinned ns-3 environment and g++')
class CongestedOrbitalEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.config = orbital_workload('normal', duration=3.0)
        cls.results = {}
        for policy in ('propagation', 'predictive'):
            directory = Path(cls.temp.name) / policy
            cls.results[policy] = run(cls.config, directory, policy=policy)
            cls.results[policy]['_directory'] = directory
            assert (directory / 'engine.stderr').read_text() == ''

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_orbital_run_actually_congests(self):
        result = self.results['propagation']
        self.assertGreater(sum(f['dropped'] for f in result['flows']), 100)
        self.assertGreaterEqual(max(q['max_packets'] for q in result['queues']), 20)
        for flow in result['flows']:
            self.assertEqual(flow['generated'], flow['delivered'] + flow['dropped'] + flow['in_flight'])
        deliveries = result['qos']['classes']
        for name in ('CONTROL', 'REALTIME', 'BULK'):
            self.assertGreater(deliveries[name]['udp_delivered'], 0)

    def test_routing_policy_changes_the_outcome(self):
        propagation = self.results['propagation']
        predictive = self.results['predictive']
        propagation_drops = sum(f['dropped'] for f in propagation['flows'])
        predictive_drops = sum(f['dropped'] for f in predictive['flows'])
        self.assertNotEqual(propagation_drops, predictive_drops,
                            'the scenario must discriminate between routing policies')
        self.assertGreater(sum(f['route_changes'] for f in predictive['flows']), 0)

    def test_forecasts_are_scored_inside_the_run_window(self):
        prediction = self.results['predictive']['prediction']
        self.assertGreater(prediction['queue']['samples'], 0)
        self.assertGreater(prediction['orbital']['samples'], 0)
        self.assertIsNotNone(prediction['orbital']['availability_accuracy'])
        self.assertIsNotNone(prediction['queue']['mae_bytes'])
        self.assertGreater(prediction['decision_count'], 0)

    def test_results_file_does_not_duplicate_the_event_log(self):
        result = self.results['propagation']
        directory = result['_directory']
        self.assertTrue(result['events'])
        serialized = json.loads((directory / 'results.json').read_text())
        self.assertNotIn('events', serialized)
        self.assertGreater((directory / 'events.tsv').stat().st_size, 0)
        manifest = json.loads((directory / 'manifest.json').read_text())
        self.assertEqual(manifest['result_sha256'],
                         hashlib.sha256((directory / 'results.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
