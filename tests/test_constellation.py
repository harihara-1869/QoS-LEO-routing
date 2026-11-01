"""Core geometry checks retained from the original foundation tests."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from skyfield.api import load

from constellation.omm import generate_omm_csv, get_satellite_data
from constellation.topology import (
    LinkType,
    LogicalConfig,
    LogicalTopology,
    link_clear_of_earth,
)


class ConstellationTests(unittest.TestCase):
    def test_occlusion_and_degenerate_points(self):
        self.assertTrue(
            link_clear_of_earth(np.array([7000.0, 0, 0]), np.array([7000.0, 1000, 0]))
        )
        self.assertFalse(
            link_clear_of_earth(np.array([7000.0, 0, 0]), np.array([-7000.0, 0, 0]))
        )
        self.assertFalse(link_clear_of_earth(np.ones(3), np.ones(3)))
        self.assertFalse(link_clear_of_earth(np.full(3, np.nan), np.ones(3)))

    def test_single_satellite_has_no_self_link(self):
        with tempfile.TemporaryDirectory() as temp:
            csv = str(Path(temp) / "s.csv")
            generate_omm_csv(csv, 1, sats_per_plane=1)
            sats = get_satellite_data(csv_file=csv)
            topology = LogicalTopology(sats, ground_stations=[])
            _, links, _, _ = topology.compute(load.timescale().utc(2025, 1, 1))
            self.assertFalse(links)

    def test_plane_grouping_range_gate_and_ground_visibility(self):
        from skyfield.api import wgs84

        with tempfile.TemporaryDirectory() as temp:
            csv = str(Path(temp) / "s.csv")
            generate_omm_csv(csv, 25, sats_per_plane=4)
            sats = get_satellite_data(csv_file=csv)
            topology = LogicalTopology(
                sats, LogicalConfig(isl_max_km=1), ground_stations=[]
            )
            self.assertEqual(len({n.orbit_id for n in topology.nodes}), 25)
            t = load.timescale().utc(2025, 1, 1)
            _, links, _, _ = topology.compute(t)
            self.assertFalse(links)
            sat = sats[0]
            subpoint = wgs84.subpoint(sat.at(t))
            gs = [
                ("below", subpoint.latitude.degrees, subpoint.longitude.degrees, 0),
                (
                    "opposite",
                    -subpoint.latitude.degrees,
                    (subpoint.longitude.degrees + 360) % 360 - 180,
                    0,
                ),
            ]
            topology = LogicalTopology([sat], ground_stations=gs)
            _, links, added, removed = topology.compute(t)
            self.assertEqual(
                {b for kind, a, b in links if kind == LinkType.UDL}, {"below"}
            )
            self.assertEqual(links, added)
            _, _, added, removed = topology.compute(t)
            self.assertFalse(added or removed)


if __name__ == "__main__":
    unittest.main()
