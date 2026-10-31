"""Phase 1 route-feasibility baseline. This is NOT a packet engine."""
from datetime import datetime
from skyfield.api import load
from schedule_core import ScheduleCore
from traffic_module import TrafficModule
from logic_module import LogicalTopology

class SimulationManager:
    def __init__(self, satellites, epoch="2025-01-01T00:00:00+00:00", config=None, ground_stations=None, orbital_start_s=0.0):
        self.orbital_start_s = orbital_start_s
        self.core = ScheduleCore()
        self.topology = LogicalTopology(satellites, config, ground_stations)
        self.traffic = TrafficModule(self)
        self.ts = load.timescale()
        dt = datetime.fromisoformat(epoch.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('epoch requires an explicit timezone')
        self.start_epoch = self.ts.from_datetime(dt)
        self.dataset = []
        self.snapshots = []
        self.routed_packets = 0
        self.unreachable_packets = 0
        self._graph = None
        self._graph_time = None

    def get_sim_time(self, seconds_from_start):
        return self.ts.tt_jd(self.start_epoch.whole, self.start_epoch.tt_fraction + (seconds_from_start+self.orbital_start_s)/86400)

    def update_topology(self):
        if self._graph_time == self.core.current_time:
            return self._graph
        t = self.get_sim_time(self.core.current_time)
        pos, links, added, removed = self.topology.compute(t)
        gs = {name: self.topology.get_gs_position(name, t) for name, *_ in self.topology.ground_stations}
        self._graph = self.topology.construct_unified_graph(pos, gs)
        self._graph_time = self.core.current_time
        self.snapshots.append({"time_s": self.core.current_time,
                               "nodes": self._graph.vs['name'],
                               "positions_km": {node.sat.name: point.tolist() for node, point in pos.items()},
                               "links": [{"a": self._graph.vs[e.source]['name'],
                                          "b": self._graph.vs[e.target]['name'], "distance_km": e['weight'],
                                          "capacity_bps": int(e['capacity_bps'])}
                                         for e in self._graph.es],
                               "added": len(added), "removed": len(removed)})
        return self._graph

    def inject_packet(self, packet):
        g = self.update_topology()
        path = self.topology.get_path(g, packet.src, packet.dst)
        if path:
            self.routed_packets += 1
            self.collect_data(g, packet, path)
        else:
            self.unreachable_packets += 1
        # Route existence is not delivery; a Phase 2 backend owns packet outcomes.

    def collect_data(self, g, packet, optimal_path):
        self.dataset.append({"time": self.core.current_time, "node_names": g.vs['name'],
                             "src": packet.src, "dst": packet.dst, "target_path": optimal_path})

    def run_step(self, time, interval):
        self.update_topology()
        self.traffic.on_packet_generation(time, interval)
        self.core.schedule(time + interval, 2, self.run_step, interval)
