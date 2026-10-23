import math
import numpy as np
from collections import defaultdict
from skyfield.api import EarthSatellite, wgs84
from dataclasses import dataclass
from enum import Enum, auto
import igraph as ig

#Configuration Section

CSV_FILENAME = 'customconstellation.csv'
MAX_SATS = 100
TIME_MULTIPLIER = 100.0

EARTH_RADIUS = 6371.0
SCALE = 1.0/6371.0

@dataclass
class LogicalConfig:
    isl_max_km: float = 5000
    iol_cone_deg: float = 60
    min_elev_deg: float = 5
    enable_iol: bool = False  # needs an explicit optical terminal model

LOGICAL_CONFIG = LogicalConfig()

GROUND_STATIONS = [
    ("GS_INDIA", 28.6139, 77.2090, 0),
    ("GS_USA", 37.7749, -122.4194, 0),
    ("GS_BRAZIL", -23.5505, -46.6333, 0),
    ("GS_AUSTRALIA", -33.8688, 151.2093, 0),
    ("NP",90.0,0.0,0),
    ("SP",-90.0,0.0,0),
]

# Earth Occlusion Check

def link_clear_of_earth(p1, p2):
    p1, p2 = np.asarray(p1), np.asarray(p2)
    if not (np.all(np.isfinite(p1)) and np.all(np.isfinite(p2))):
        return False
    d = p2 - p1
    squared = np.dot(d, d)
    if squared <= 1e-18:
        return False
    closest = p1 + np.clip(-np.dot(p1, d) / squared, 0, 1) * d
    return bool(np.linalg.norm(closest) > EARTH_RADIUS)

# Data Structure

@dataclass(eq=False)
class SatelliteNode:
    sat: EarthSatellite
    orbit_id: int
    index: int

# Link Type

class LinkType(Enum):
    ISL_INTRA = auto()
    ISL_INTER = auto()
    IOL = auto()
    UDL = auto()
    
# Logical Module

class LogicalTopology:

    def __init__(self, sats, config=None, ground_stations=None):
        self.nodes = self._group_orbits(sats)
        names = [node.sat.name for node in self.nodes]
        if len(names) != len(set(names)):
            raise ValueError("Satellite names must be unique")
        self.cfg = config or LogicalConfig()
        if not (math.isfinite(self.cfg.isl_max_km) and self.cfg.isl_max_km > 0
                and 0 <= self.cfg.min_elev_deg <= 90 and 0 <= self.cfg.iol_cone_deg <= 180):
            raise ValueError("Invalid link configuration")
        self.ground_stations = list(GROUND_STATIONS if ground_stations is None else ground_stations)
        gs_names = [gs[0] for gs in self.ground_stations]
        if len(gs_names) != len(set(gs_names)) or set(gs_names) & set(names):
            raise ValueError("Ground station names must be unique and distinct from satellites")
        for _, lat, lon, height in self.ground_stations:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180 and math.isfinite(height)):
                raise ValueError("Invalid ground station coordinates")
        self.links = set()
        self.prev_links = set()
        self.last_update_time = None

    def _group_orbits(self, sats):
        groups = defaultdict(list)
        for sat in sats:
            inc = round(sat.model.inclo, 6)
            raan = round(sat.model.nodeo, 6)
            groups[(inc, raan)].append(sat)
        nodes = []
        orbit_id = 0

        for key in sorted(groups.keys()):
            group = groups[key]
            group.sort(key = lambda s: (s.model.mo, s.name))
            for i, sat in enumerate(group):
                nodes.append(SatelliteNode(sat, orbit_id, i))
            
            orbit_id += 1
        
        return nodes
    
    def compute(self, t):
        pos = {n: n.sat.at(t).position.km for n in self.nodes}
        if any(not np.all(np.isfinite(point)) for point in pos.values()):
            raise ValueError("Non-finite satellite position; check epoch and OMM inputs")
        orbits = defaultdict(list)
        for n in self.nodes:
            orbits[n.orbit_id].append(n)
        
        candidate_links = set()

        # same-orbit ISLs
        for orbit_nodes in orbits.values():
            N = len(orbit_nodes)
            for i, n in enumerate(orbit_nodes):
                for nb in (orbit_nodes[(i - 1) % N], orbit_nodes[(i + 1) % N]):
                    if n is not nb and np.linalg.norm(pos[n] - pos[nb]) <= self.cfg.isl_max_km and link_clear_of_earth(pos[n], pos[nb]):
                        a, b = sorted((n, nb), key = lambda node: node.sat.name)
                        candidate_links.add(
                            (LinkType.ISL_INTRA, a, b)
                        )
        
        # adjacent orbit ISLs
        for oid in orbits:
            for adj in (oid-1, oid+1):
                if adj not in orbits:
                    continue

                for n in orbits[oid]:
                    nearest = min(
                        orbits[adj],
                        key = lambda m: np.linalg.norm(pos[n] - pos[m])
                    )

                    dist = np.linalg.norm(pos[n] - pos[nearest])

                    if dist <= self.cfg.isl_max_km and link_clear_of_earth(pos[n], pos[nearest]):
                        a, b = sorted((n, nearest), key = lambda node: node.sat.name)
                        candidate_links.add(
                            (LinkType.ISL_INTER, a, b)
                        )

        # IOL cone models
        for a in (self.nodes if self.cfg.enable_iol else []):
            for b in self.nodes:
                if a is b:
                    continue

                v = pos[b] - pos[a]
                nadir = -pos[a]

                cos_angle = np.dot(v, nadir) / (
                    np.linalg.norm(v) * np.linalg.norm(nadir)
                )

                cos_angle = np.clip(cos_angle, -1.0, 1.0)
                angle = math.degrees(math.acos(cos_angle))

                if angle <= self.cfg.iol_cone_deg and link_clear_of_earth(pos[a], pos[b]):
                    a_norm, b_norm = sorted((a, b), key = lambda node: node.sat.name)
                    candidate_links.add(
                        (LinkType.IOL, a_norm, b_norm)
                    )

        # UDL satellite ground links
        for n in self.nodes:
            for name, lat, lon, h in self.ground_stations:
                gs = wgs84.latlon(lat, lon, elevation_m = h)

                alt, _, _ = (n.sat - gs).at(t).altaz()
                if alt.degrees < self.cfg.min_elev_deg:
                    continue

                gs_pos = gs.at(t).position.km

                # Skyfield elevation uses WGS84; a mean-radius sphere incorrectly
                # occludes ground stations near the poles. Elevation gates UDLs.
                if np.all(np.isfinite(gs_pos)):
                    candidate_links.add(
                        (LinkType.UDL, n, name)
                    )

        new_links = candidate_links - self.links
        removed_links = self.links - candidate_links
        self.prev_links = self.links
        self.links = candidate_links
        self.last_update_time = t

        return pos, self.links, new_links, removed_links
    
    def construct_unified_graph(self, pos, gs_positions):
        num_sats = len(self.nodes)
        num_gs = len(self.ground_stations)

        g = ig.Graph(n= num_sats + num_gs, directed=False)

        gs_names = [gs[0] for gs in self.ground_stations]
        g.vs["name"] = [n.sat.name for n in self.nodes] + gs_names
        g.vs["type"] = ["satellite"] * num_sats + ["ground_station"] * num_gs

        sat_to_id = {node: i for i, node in enumerate(self.nodes)}
        gs_to_id = {name: i + num_sats for i, name in enumerate(gs_names)}

        edges = []
        weights = []

        for link_type, a, b in sorted(self.links, key=lambda link: (link[0].value, link[1].sat.name, link[2] if isinstance(link[2], str) else link[2].sat.name)):
            if link_type in (LinkType.ISL_INTRA, LinkType.ISL_INTER, LinkType.IOL):
                u = sat_to_id[a]
                v = sat_to_id[b]
                dist = np.linalg.norm(pos[a] - pos[b])
            
            elif link_type == LinkType.UDL:
                u = sat_to_id[a]
                v = gs_to_id[b]
                dist = np.linalg.norm(pos[a] - gs_positions[b])

            else:
                continue

            if not np.isfinite(dist):
                continue

            edges.append((u, v))
            weights.append(dist)

        g.add_edges(edges)
        g.es["weight"] = weights

        return g
    
    @staticmethod
    def get_path(g, start_name, end_name):
        
        try:
            id_a = g.vs.find(name = start_name).index
            id_b = g.vs.find(name = end_name).index
        except ValueError:
            return []
        
        nan_edges = [e.index for e in g.es if np.isnan(e["weight"])]
        if nan_edges:
            g.delete_edges(nan_edges)

        try:
            path_indices = g.get_shortest_paths(
                id_a,
                to = id_b,
                weights = g.es["weight"],
                output = "vpath"
            )[0]
            return [g.vs[i]["name"] for i in path_indices]
        
        except Exception as e:
            print(f"Djikstra failed: {e}")
            return []
    def get_gs_position(self, name, t):
    
    # 1. Find the GS metadata from your GROUND_STATIONS list
        gs_metadata = next((gs for gs in self.ground_stations if gs[0] == name), None)
        if not gs_metadata:
            raise ValueError(f"Ground Station {name} not found in configuration.")

        _, lat, lon, alt = gs_metadata

        # 2. Create the wgs84 geodetic object
        gs_geodetic = wgs84.latlon(lat, lon, elevation_m=alt)

        # 3. Compute the position at time 't'
        # This converts Geodetic (Lat/Lon) -> ECI (X, Y, Z) based on Earth's rotation
        pos_eci = gs_geodetic.at(t).position.km
        
        return pos_eci