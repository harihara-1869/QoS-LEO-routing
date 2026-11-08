"""Feature encoding and neuro-symbolic tree decoding for learned routing."""
from copy import deepcopy
import heapq
import math
import numpy as np

from packet_backend.qos import CLASSES


class GraphObservationEncoder:
    """Normalizes raw ns-3 controller observations into compact fixed-size feature vectors."""

    def __init__(self, max_links: int = 500, max_flows: int = 20):
        self.max_links = max_links
        self.max_flows = max_flows
        # Feature sizes:
        # Per link: 16 features (delay, capacity, is_ground, lifetime, and per-class: queue_bytes, arrival_rate, drop_rate)
        self.link_feat_dim = 16
        # Per flow: 5 features (class_id, rate, deadline, payload_size, active)
        self.flow_feat_dim = 5
        self.total_dim = (self.max_links * 2 * self.link_feat_dim) + (self.max_flows * self.flow_feat_dim)

    def encode(self, observation: dict, orbital_forecasts: dict | None = None) -> np.ndarray:
        now = observation['time_s']
        edges = {e['id']: e for e in observation['links']}
        queues = {(q['link_id'], q['direction']): q for q in observation['queues']}
        qos_weights = observation.get('qos', {}).get('weights', {'CONTROL': 4, 'REALTIME': 2, 'BULK': 1})
        total_weight = sum(qos_weights.values())

        link_features = []
        for edge_id, edge in sorted(edges.items()):
            a, b = edge['a'], edge['b']
            is_ground = 1.0 if (a in observation.get('non_transit_nodes', []) or b in observation.get('non_transit_nodes', [])) else 0.0
            cap_mbps = edge['capacity_bps'] / 1e6
            delay_ms = edge['delay_s'] * 1000.0

            # Orbital lifetime
            lifetime_s = 60.0
            if orbital_forecasts and edge_id in orbital_forecasts:
                lt = orbital_forecasts[edge_id].get('lifetime_lower_s')
                if lt is not None:
                    lifetime_s = min(float(lt), 60.0)

            # Two directions: 0 (a->b), 1 (b->a)
            for d in (0, 1):
                q = queues.get((edge_id, d), {})
                classes = q.get('classes', {})
                c0 = classes.get('CONTROL', {})
                c1 = classes.get('REALTIME', {})
                c2 = classes.get('BULK', {})

                feat = [
                    delay_ms / 100.0,
                    cap_mbps / 100.0,
                    is_ground,
                    lifetime_s / 60.0,
                    # Queue lengths in KB
                    c0.get('bytes', 0) / 10000.0,
                    c1.get('bytes', 0) / 10000.0,
                    c2.get('bytes', 0) / 10000.0,
                    # Arrived bytes
                    c0.get('arrived_bytes', 0) / 100000.0,
                    c1.get('arrived_bytes', 0) / 100000.0,
                    c2.get('arrived_bytes', 0) / 100000.0,
                    # Rejected bytes
                    c0.get('rejected_bytes', 0) / 50000.0,
                    c1.get('rejected_bytes', 0) / 50000.0,
                    c2.get('rejected_bytes', 0) / 50000.0,
                    # DRR nominal shares
                    qos_weights['CONTROL'] / total_weight,
                    qos_weights['REALTIME'] / total_weight,
                    qos_weights['BULK'] / total_weight,
                ]
                link_features.append(feat)

        # Pad link features if necessary
        link_feats_arr = np.zeros((self.max_links * 2, self.link_feat_dim), dtype=np.float32)
        n_dir_links = min(len(link_features), self.max_links * 2)
        if n_dir_links > 0:
            link_feats_arr[:n_dir_links] = np.array(link_features[:n_dir_links], dtype=np.float32)

        # Active flows encoding
        flow_features = np.zeros((self.max_flows, self.flow_feat_dim), dtype=np.float32)
        active_flows = observation.get('active_flows', [])
        for idx, flow in enumerate(active_flows[:self.max_flows]):
            flow_features[idx] = [
                float(flow['class_id']),
                float(flow.get('rate', 0.0)) / 1e6,
                float(flow.get('deadline_s', 0.1) or 0.1),
                float(flow.get('size', 1000)) / 1500.0,
                1.0,  # active indicator
            ]

        flat_state = np.concatenate([link_feats_arr.flatten(), flow_features.flatten()])
        return flat_state


class NeuroSymbolicTreeDecoder:
    """Decodes continuous learned edge potentials into strictly loop-free routing trees."""

    def __init__(self,
                 potential_scale: float = 0.20,
                 drain_horizon_s: float = 1.0,
                 ground_acq_s: float = 0.15,
                 change_penalty_s: float = 0.005):
        self.potential_scale = potential_scale
        self.drain_horizon_s = drain_horizon_s
        self.ground_acq_s = ground_acq_s
        self.change_penalty_s = change_penalty_s
        self.previous_routes = {}

    def reset(self):
        self.previous_routes.clear()

    def decode(self,
               observation: dict,
               potentials: np.ndarray,
               orbital_forecasts: dict | None = None) -> dict[tuple[int, int, int], int]:
        """Converts network potentials into cycle-free routing trees for all classes.

        Parameters:
            observation: Current ns-3 observation.
            potentials: Array of shape (num_edges, 3) with learned potential perturbations in [0, 1].
            orbital_forecasts: Dict mapping edge_id to predicted link lifetimes.

        Returns:
            Dictionary mapping (class_id, source, destination) -> next_hop.
        """
        nodes = observation['nodes']
        links = observation['links']
        non_transit = set(observation.get('non_transit_nodes', []))
        queues = {(q['link_id'], q['direction']): q for q in observation['queues']}
        weights = observation.get('qos', {}).get('weights', {'CONTROL': 4, 'REALTIME': 2, 'BULK': 1})
        total_weight = sum(weights.values())

        routes_out = {}
        edge_index_map = {edge['id']: i for i, edge in enumerate(links)}

        for c, name in enumerate(CLASSES):
            w_class = weights[name] / total_weight

            def edge_cost(edge, direction, a, b):
                e_id = edge['id']
                prop_delay = edge['delay_s']
                cap = max(edge['capacity_bps'], 1.0)

                q_entry = queues.get((e_id, direction), {})
                c_bytes = q_entry.get('classes', {}).get(name, {}).get('bytes', 0)

                # 1. Base queuing delay estimate under DRR
                service_rate_bps = cap * w_class
                queue_delay = (c_bytes * 8.0) / max(service_rate_bps, 1.0)

                # 2. Learned potential perturbation
                p_idx = edge_index_map.get(e_id, 0)
                learned_potential = 0.0
                if potentials is not None and p_idx < len(potentials):
                    learned_potential = float(potentials[p_idx, c]) * self.potential_scale

                # 3. Proactive Orbital-Drain Barrier Potential
                drain_penalty = 0.0
                if orbital_forecasts and e_id in orbital_forecasts:
                    fc = orbital_forecasts[e_id]
                    # Only apply proactive barrier if the link is uncensored (confirmed to drop within horizon)
                    if not fc.get('censored', True):
                        lt = fc.get('lifetime_lower_s')
                        if lt is not None:
                            is_ground = (a in non_transit or b in non_transit)
                            t_guard = self.ground_acq_s if is_ground else 0.05
                            if lt <= t_guard:
                                # Link will drop imminently; mark unusable to prevent in-flight drop
                                return None
                            elif lt <= t_guard + self.drain_horizon_s:
                                # Smooth continuous barrier as lifetime expires
                                drain_penalty = 0.02 / max(lt - t_guard, 1e-4)

                # 4. Hysteresis switching penalty to prevent route churn
                hysteresis = 0.0
                old_hop = self.previous_routes.get((c, a, None))
                if old_hop is not None and old_hop != b:
                    hysteresis = self.change_penalty_s

                total_cost = prop_delay + queue_delay + learned_potential + drain_penalty + hysteresis
                return max(total_cost, 1e-6)

            # Build destination trees for each destination
            for dst in observation['destinations']:
                # Run reverse Dijkstra from destination
                reverse = [[] for _ in nodes]
                for edge in links:
                    for direction, (u, v) in enumerate(((edge['a'], edge['b']), (edge['b'], edge['a']))):
                        cost = edge_cost(edge, direction, u, v)
                        if cost is not None:
                            reverse[v].append((u, cost))

                distances = {dst: 0.0}
                pending = [(0.0, dst)]
                class_dst_routes = {}

                while pending:
                    dist, node = heapq.heappop(pending)
                    if dist != distances[node]:
                        continue
                    if node != dst and node in non_transit:
                        continue
                    for neighbor, weight in sorted(reverse[node]):
                        candidate = dist + weight
                        if candidate < distances.get(neighbor, math.inf):
                            distances[neighbor] = candidate
                            class_dst_routes[neighbor] = node
                            heapq.heappush(pending, (candidate, neighbor))

                for src, nxt in class_dst_routes.items():
                    routes_out[c, src, dst] = nxt
                    self.previous_routes[c, src, None] = nxt

        return routes_out

