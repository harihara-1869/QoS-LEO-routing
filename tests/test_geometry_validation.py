"""Independent checks of the orbital and link geometry used by the simulator.

These are cross-checks against separately written arithmetic, not comparisons
with the same code path. They do not validate SGP4 against an external
ephemeris service; the frame rotation from GCRS to Earth-fixed is Skyfield's.
"""
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from skyfield.api import load, wgs84
from skyfield.framelib import itrs

from constellation.topology import (EARTH_RADIUS, LinkType, LogicalConfig, LogicalTopology,
                          link_clear_of_earth)
from packet_backend.scenario import C_KM_S, prepare
from constellation.omm import generate_omm_csv, get_satellite_data

MU = 398600.4418


def kepler_position(model, seconds):
    """Two-body propagation from the mean elements, independent of SGP4."""
    n = model.no_kozai / 60.0
    a = (MU / n**2) ** (1.0 / 3.0)
    mean_anomaly = model.mo + n * seconds
    eccentric = mean_anomaly
    for _ in range(60):
        eccentric -= (eccentric - model.ecco * math.sin(eccentric) - mean_anomaly) / (
            1 - model.ecco * math.cos(eccentric))

    def rot_x(angle):
        c, s = math.cos(angle), math.sin(angle)
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])

    def rot_z(angle):
        c, s = math.cos(angle), math.sin(angle)
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

    planar = np.array([a * (math.cos(eccentric) - model.ecco),
                       a * math.sqrt(1 - model.ecco**2) * math.sin(eccentric), 0.0])
    return rot_z(model.nodeo) @ rot_x(model.inclo) @ rot_z(model.argpo) @ planar


def station_ecef(latitude, longitude, height_km):
    """WGS84 geodetic to Earth-centred cartesian, written from the definition."""
    semi_major, flattening = 6378.137, 1 / 298.257223563
    eccentricity_sq = flattening * (2 - flattening)
    phi, lam = math.radians(latitude), math.radians(longitude)
    prime_vertical = semi_major / math.sqrt(1 - eccentricity_sq * math.sin(phi) ** 2)
    return np.array([(prime_vertical + height_km) * math.cos(phi) * math.cos(lam),
                     (prime_vertical + height_km) * math.cos(phi) * math.sin(lam),
                     (prime_vertical * (1 - eccentricity_sq) + height_km) * math.sin(phi)])


def elevation_angle(satellite_ecef, latitude, longitude, height_km=0.0):
    """Topocentric elevation from an Earth-fixed position, independent of Skyfield."""
    phi, lam = math.radians(latitude), math.radians(longitude)
    east = np.array([-math.sin(lam), math.cos(lam), 0.0])
    north = np.array([-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi)])
    up = np.array([math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi)])
    offset = satellite_ecef - station_ecef(latitude, longitude, height_km)
    return math.degrees(math.atan2(offset @ up, math.hypot(offset @ east, offset @ north)))


class OrbitalPropagationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.csv = Path(cls.temp.name) / 'orbit.csv'
        generate_omm_csv(cls.csv, 4, sats_per_plane=8)
        cls.satellites = get_satellite_data(csv_file=cls.csv)
        cls.timescale = load.timescale()
        cls.epoch = cls.timescale.utc(2025, 1, 1)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_two_body_rate_matches_sgp4(self):
        """Kepler and SGP4 must advance at the same rate over five minutes.

        The absolute offset is tens of km because SGP4 mean elements differ from
        osculating elements; a rate error is what would indicate a broken model.
        """
        for satellite in self.satellites:
            reference = satellite.at(self.epoch).position.km
            base = np.linalg.norm(kepler_position(satellite.model, 0) - reference)
            self.assertLess(base, 100.0)
            radius = np.linalg.norm(reference)
            self.assertLess(abs(np.linalg.norm(kepler_position(satellite.model, 0)) - radius), 20.0)
            for seconds in (30, 60, 300):
                propagated = satellite.at(self.epoch + seconds / 86400.0).position.km
                drift = abs(np.linalg.norm(kepler_position(satellite.model, seconds) - propagated) - base)
                self.assertLess(drift, 25.0, f'{satellite.name} drifted {drift:.2f} km at {seconds}s')

    def test_altitude_and_period_are_physical(self):
        for satellite in self.satellites[:4]:
            radius = np.linalg.norm(satellite.at(self.epoch).position.km)
            self.assertGreater(radius, EARTH_RADIUS + 400)
            self.assertLess(radius, EARTH_RADIUS + 700)
            period = 2 * math.pi * math.sqrt((radius) ** 3 / MU)
            self.assertGreater(period, 5400)
            self.assertLess(period, 6000)


class ElevationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        csv = Path(cls.temp.name) / 'orbit.csv'
        generate_omm_csv(csv, 6, sats_per_plane=10)
        cls.satellites = get_satellite_data(csv_file=csv)
        cls.timescale = load.timescale()
        cls.epoch = cls.timescale.utc(2025, 1, 1)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_enu_elevation_matches_skyfield(self):
        stations = [(28.6139, 77.2090), (37.7749, -122.4194),
                    (-33.8688, 151.2093), (0.0, 0.0), (89.0, 10.0), (-89.0, -45.0)]
        for latitude, longitude in stations:
            ground = wgs84.latlon(latitude, longitude)
            for satellite in self.satellites:
                reference = (satellite - ground).at(self.epoch).altaz()[0].degrees
                earth_fixed = np.array(satellite.at(self.epoch).frame_xyz(itrs).km)
                mine = elevation_angle(earth_fixed, latitude, longitude)
                self.assertAlmostEqual(mine, reference, places=6)

    def test_visible_set_matches_elevation_mask(self):
        subpoint = wgs84.subpoint(self.satellites[0].at(self.epoch))
        ground = [('masked', subpoint.latitude.degrees, subpoint.longitude.degrees, 0)]
        topology = LogicalTopology(self.satellites,
                                   LogicalConfig(min_elev_deg=5,
                                                 ground_links_per_station=len(self.satellites)),
                                   ground_stations=ground)
        _, links, _, _ = topology.compute(self.epoch)
        linked = {node.sat.name for kind, node, name in links if kind == LinkType.UDL}
        expected = {satellite.name for satellite in self.satellites
                    if (satellite - wgs84.latlon(subpoint.latitude.degrees,
                                                 subpoint.longitude.degrees))
                    .at(self.epoch).altaz()[0].degrees >= 5}
        self.assertTrue(expected)
        self.assertEqual(linked, expected)


class LinkGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        csv = Path(cls.temp.name) / 'orbit.csv'
        generate_omm_csv(csv, 6, sats_per_plane=10)
        cls.satellites = get_satellite_data(csv_file=csv)
        cls.timescale = load.timescale()
        cls.epoch = cls.timescale.utc(2025, 1, 1)
        cls.config = LogicalConfig(ground_capacity_bps=25000000)
        cls.topology = LogicalTopology(cls.satellites, cls.config,
                                       ground_stations=[('A', 28.6139, 77.2090, 0),
                                                        ('B', -33.8688, 151.2093, 0)])
        cls.positions, cls.links, _, _ = cls.topology.compute(cls.epoch)
        cls.graph = cls.topology.construct_unified_graph(
            cls.positions, {name: cls.topology.get_gs_position(name, cls.epoch)
                            for name, *_ in cls.topology.ground_stations})

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_graph_distances_match_direct_geometry(self):
        names, kinds = self.graph.vs['name'], self.graph.vs['type']
        by_name = {node.sat.name: node for node in self.topology.nodes}
        checked = 0
        for edge in self.graph.es:
            if kinds[edge.source] != 'satellite' or kinds[edge.target] != 'satellite':
                continue
            a, b = names[edge.source], names[edge.target]
            expected = np.linalg.norm(self.positions[by_name[a]] - self.positions[by_name[b]])
            self.assertAlmostEqual(edge['weight'], expected, places=6)
            checked += 1
        self.assertGreater(checked, 50)

    def test_every_isl_respects_range_and_occlusion(self):
        kinds = self.graph.vs['type']
        checked = 0
        for edge in self.graph.es:
            if kinds[edge.source] != 'satellite' or kinds[edge.target] != 'satellite':
                continue
            self.assertLessEqual(edge['weight'], self.config.isl_max_km)
            checked += 1
        self.assertGreater(checked, 50)

    def test_occlusion_agrees_with_independent_chord_calculation(self):
        a = np.array([7000.0, 0.0, 0.0])
        for angle_deg in (1, 5, 10, 20, 40, 60, 90, 150, 179):
            b = np.array([7000.0 * math.cos(math.radians(angle_deg)),
                           0.0, 7000.0 * math.sin(math.radians(angle_deg))])
            closest = 7000.0 * math.cos(math.radians(angle_deg) / 2) if angle_deg <= 180 else 0.0
            expected = closest > EARTH_RADIUS
            self.assertEqual(link_clear_of_earth(a, b), expected, f'{angle_deg} deg')

    def test_capacities_are_differentiated_by_link_class(self):
        kinds = self.graph.vs['type']
        ground_edges = 0
        for edge in self.graph.es:
            ground = 'ground_station' in (kinds[edge.source], kinds[edge.target])
            self.assertEqual(edge['capacity_bps'],
                             self.config.ground_capacity_bps if ground else self.config.isl_capacity_bps)
            ground_edges += ground
        self.assertGreaterEqual(ground_edges, 1)

    def test_explicit_distance_converts_to_propagation_delay(self):
        config = {'schema_version': 1, 'duration_s': 1, 'topology': {
            'nodes': ['a', 'b'],
            'snapshots': [{'time_s': 0, 'links': [{'a': 'a', 'b': 'b', 'distance_km': C_KM_S}]}]},
            'flows': [{'flow_id': 1, 'src': 'a', 'dst': 'b', 'start_time': 0, 'end_time': 1,
                       'packet_size_bytes': 100, 'data_rate_bps': 1000}]}
        with tempfile.TemporaryDirectory() as temp:
            plan = prepare(config, Path(temp))
        self.assertAlmostEqual(plan['snapshots'][0]['links'][0]['delay_s'], 1.0, places=12)


class TopologyStructureTests(unittest.TestCase):
    """The corrected connectivity rules: fixed terminal budget, bounded ground access."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        csv = Path(cls.temp.name) / 'orbit.csv'
        generate_omm_csv(csv, 10, sats_per_plane=20)
        cls.satellites = get_satellite_data(csv_file=csv)
        cls.timescale = load.timescale()
        cls.epoch = cls.timescale.utc(2025, 1, 1)
        cls.stations = [('GS_A', 28.6139, 77.2090, 0), ('GS_B', -33.8688, 151.2093, 0),
                        ('GS_C', 37.7749, -122.4194, 0), ('GS_D', -23.5505, -46.6333, 0)]
        cls.topology = LogicalTopology(cls.satellites, LogicalConfig(), cls.stations)
        cls.positions, cls.links, _, _ = cls.topology.compute(cls.epoch)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def isl_degree(self):
        degree = {node.sat.name: 0 for node in self.topology.nodes}
        for kind, a, b in self.links:
            if kind in (LinkType.ISL_INTRA, LinkType.ISL_INTER):
                degree[a.sat.name] += 1
                degree[b.sat.name] += 1
        return degree

    def test_isl_degree_is_bounded_by_the_terminal_budget(self):
        degree = self.isl_degree()
        self.assertLessEqual(max(degree.values()), 4)
        self.assertGreaterEqual(min(degree.values()), 2)
        # Interior planes carry two same-plane and two cross-plane links.
        self.assertGreaterEqual(sum(value == 4 for value in degree.values()), 120)

    def test_cross_plane_links_are_one_per_satellite_per_adjacent_plane(self):
        cross = [(a.sat.name, b.sat.name) for kind, a, b in self.links if kind == LinkType.ISL_INTER]
        by_plane = {}
        for a, b in cross:
            plane_a, plane_b = a.split('-')[1], b.split('-')[1]
            self.assertEqual(abs(int(plane_a) - int(plane_b)), 1, 'cross-plane link skips a plane')
            by_plane.setdefault(a, []).append(b)
            by_plane.setdefault(b, []).append(a)
        for satellite, neighbours in by_plane.items():
            planes = [n.split('-')[1] for n in neighbours]
            self.assertEqual(len(planes), len(set(planes)), f'{satellite} has two links into one plane')

    def test_ground_station_links_are_bounded(self):
        for name, *_ in self.stations:
            count = sum(1 for kind, node, station in self.links if kind == LinkType.UDL and station == name)
            self.assertEqual(count, 1, f'{name} formed {count} ground links')
        self.assertEqual(len([link for link in self.links if link[0] == LinkType.UDL]), len(self.stations))

    def test_ground_station_selects_highest_elevation_satellite(self):
        for name, lat, lon, _ in self.stations:
            ground = wgs84.latlon(lat, lon)
            elevations = {satellite.name: (satellite - ground).at(self.epoch).altaz()[0].degrees
                          for satellite in self.satellites}
            chosen = next(node.sat.name for kind, node, station in self.links
                          if kind == LinkType.UDL and station == name)
            best = max(elevations, key=lambda key: (elevations[key], key))
            self.assertEqual(chosen, best)
            self.assertGreaterEqual(elevations[chosen], 5)

    def test_no_parallel_or_self_links(self):
        pairs = set()
        for kind, a, b in self.links:
            name_b = b if isinstance(b, str) else b.sat.name
            key = frozenset((a.sat.name, name_b))
            self.assertEqual(len(key), 2, 'self link')
            self.assertNotIn(key, pairs, 'parallel link')
            pairs.add(key)

    def test_invalid_capacity_configuration_is_rejected(self):
        for field, value in [('isl_capacity_bps', 0), ('ground_capacity_bps', 1.5),
                             ('ground_links_per_station', 0), ('ground_links_per_station', 10**6)]:
            config = LogicalConfig()
            setattr(config, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                LogicalTopology(self.satellites[:1], config, ground_stations=[])


if __name__ == '__main__':
    unittest.main()
