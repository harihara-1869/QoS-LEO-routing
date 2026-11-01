"""Sample the authoritative orbital topology before ns-3 packet execution."""

from datetime import datetime

from skyfield.api import load

from constellation.topology import LogicalTopology


class TopologySnapshots:
    """Convert epoch-relative physical samples into stable named graphs.

    This object only supplies orbital time/geometry and an ordered snapshot list.
    The compiled packet engine remains the sole simulation clock during execution.
    """

    def __init__(
        self,
        satellites,
        epoch="2025-01-01T00:00:00+00:00",
        config=None,
        ground_stations=None,
        orbital_start_s=0.0,
    ):
        self.orbital_start_s = orbital_start_s
        self.topology = LogicalTopology(satellites, config, ground_stations)
        self.ts = load.timescale()
        dt = datetime.fromisoformat(epoch.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("epoch requires an explicit timezone")
        self.start_epoch = self.ts.from_datetime(dt)
        self.snapshots = []
        self._graph = None
        self._graph_time = None

    def get_sim_time(self, seconds_from_start):
        return self.ts.tt_jd(
            self.start_epoch.whole,
            self.start_epoch.tt_fraction
            + (seconds_from_start + self.orbital_start_s) / 86400,
        )

    def update_topology(self, seconds_from_start):
        if self._graph_time == seconds_from_start:
            return self._graph
        t = self.get_sim_time(seconds_from_start)
        pos, links, added, removed = self.topology.compute(t)
        gs = {
            name: self.topology.get_gs_position(name, t)
            for name, *_ in self.topology.ground_stations
        }
        self._graph = self.topology.construct_unified_graph(pos, gs)
        self._graph_time = seconds_from_start
        self.snapshots.append(
            {
                "time_s": seconds_from_start,
                "nodes": self._graph.vs["name"],
                "positions_km": {
                    node.sat.name: point.tolist() for node, point in pos.items()
                },
                "links": [
                    {
                        "a": self._graph.vs[e.source]["name"],
                        "b": self._graph.vs[e.target]["name"],
                        "distance_km": e["weight"],
                        "capacity_bps": int(e["capacity_bps"]),
                    }
                    for e in self._graph.es
                ],
                "added": len(added),
                "removed": len(removed),
            }
        )
        return self._graph
