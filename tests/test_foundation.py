import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from schedule_core import ScheduleCore
from traffic_module import Flow, FlowState, TrafficModule
from logic_module import LogicalTopology, LogicalConfig, LinkType, link_clear_of_earth
from setup import generate_omm_csv, get_satellite_data
from run_scenario import run
from skyfield.api import load

class FoundationTests(unittest.TestCase):
    def test_scheduler_resume_ties_and_past(self):
        clock, events = ScheduleCore(), []
        clock.schedule(2, 1, lambda t: events.append('later'))
        clock.schedule(1, 2, lambda t: events.append('second'))
        clock.schedule(1, 1, lambda t: events.append('first'))
        clock.schedule(1, 2, lambda t: events.append('third'))
        clock.run(1)
        self.assertEqual(events, ['first', 'second', 'third'])
        clock.run(2)
        self.assertEqual(events[-1], 'later')
        with self.assertRaises(ValueError):
            clock.schedule(0, 0, print)

    def test_generation_conserves_rate_and_boundaries(self):
        class Sink:
            def __init__(self): self.packets = []
            def inject_packet(self, packet): self.packets.append(packet)
        sink = Sink()
        traffic = TrafficModule(sink)
        traffic.flows[1] = Flow(1, 'a', 'b', 0.5, 2.5, 12000)
        traffic.on_flow_start(0.5, 1)
        self.assertIn(1, traffic.active_flows)
        for t in [1, 2, 3, 4]: traffic.on_packet_generation(t, 1)
        self.assertEqual(len(sink.packets), 2)
        self.assertEqual([p.packet_id for p in sink.packets], [0, 1])
        self.assertEqual(traffic.flows[1].bytes_generated, 3000)
        self.assertEqual(traffic.flows[1].flow_state, FlowState.COMPLETED)
        traffic.flows[2] = Flow(2, 'a', 'b', 4, 5, 36000)
        traffic.on_packet_generation(5, 1)
        self.assertEqual(len(sink.packets), 5)  # all three packets injected

    def test_zero_rate_and_fractional_accumulation(self):
        class Sink:
            def inject_packet(self, packet): pass
        traffic = TrafficModule(Sink())
        traffic.flows[1] = Flow(1, 'a', 'b', 0, 10, 1200)
        traffic.flows[2] = Flow(2, 'a', 'b', 0, 10, 0)
        for t in range(1, 11): traffic.on_packet_generation(t, 1)
        self.assertEqual(traffic.flows[1].packets_generated, 1)
        self.assertEqual(traffic.flows[2].packets_generated, 0)

    def test_occlusion_and_degenerate_points(self):
        self.assertTrue(link_clear_of_earth(np.array([7000., 0, 0]), np.array([7000., 1000, 0])))
        self.assertFalse(link_clear_of_earth(np.array([7000., 0, 0]), np.array([-7000., 0, 0])))
        self.assertFalse(link_clear_of_earth(np.ones(3), np.ones(3)))
        self.assertFalse(link_clear_of_earth(np.full(3, np.nan), np.ones(3)))

    def test_single_satellite_has_no_self_link(self):
        with tempfile.TemporaryDirectory() as temp:
            csv = str(Path(temp) / 's.csv')
            generate_omm_csv(csv, 1, sats_per_plane=1)
            sats = get_satellite_data(csv_file=csv)
            topology = LogicalTopology(sats, ground_stations=[])
            _, links, _, _ = topology.compute(load.timescale().utc(2025, 1, 1))
            self.assertFalse(links)
            self.assertEqual(topology.get_path(topology.construct_unified_graph({}, {}), 'missing', 'other'), [])

    def test_plane_grouping_range_gate_and_ground_visibility(self):
        from skyfield.api import wgs84
        with tempfile.TemporaryDirectory() as temp:
            csv = str(Path(temp) / 's.csv')
            generate_omm_csv(csv, 25, sats_per_plane=4)
            sats = get_satellite_data(csv_file=csv)
            topology = LogicalTopology(sats, LogicalConfig(isl_max_km=1), ground_stations=[])
            self.assertEqual(len({n.orbit_id for n in topology.nodes}), 25)
            t = load.timescale().utc(2025, 1, 1)
            _, links, _, _ = topology.compute(t)
            self.assertFalse(links)
            sat = sats[0]
            subpoint = wgs84.subpoint(sat.at(t))
            gs = [('below', subpoint.latitude.degrees, subpoint.longitude.degrees, 0),
                  ('opposite', -subpoint.latitude.degrees, (subpoint.longitude.degrees + 360) % 360 - 180, 0)]
            topology = LogicalTopology([sat], ground_stations=gs)
            _, links, added, removed = topology.compute(t)
            self.assertEqual({b for kind, a, b in links if kind == LinkType.UDL}, {'below'})
            self.assertEqual(links, added)
            _, _, added, removed = topology.compute(t)
            self.assertFalse(added or removed)

    def test_repeatability_and_route_accounting(self):
        with tempfile.TemporaryDirectory() as temp:
            a = run('scenarios/baseline.json', Path(temp) / 'a')
            b = run('scenarios/baseline.json', Path(temp) / 'b')
            self.assertEqual(a, b)
            self.assertEqual(a['summary']['packets_generated'], 10)
            self.assertEqual(a['summary']['packets_with_route'], 10)
            self.assertEqual(len(a['topology']), 6)
            self.assertGreater(len(a['route_samples'][0]['target_path']), 2)

    def test_partial_final_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            config = json.loads(Path('scenarios/baseline.json').read_text())
            config['duration_s'] = 1.5
            scenario = Path(temp) / 'scenario.json'
            scenario.write_text(json.dumps(config))
            result = run(scenario, Path(temp) / 'out')
            self.assertEqual(result['summary']['packets_generated'], 3)
            self.assertEqual(result['topology'][-1]['time_s'], 1.5)

if __name__ == '__main__':
    unittest.main()
