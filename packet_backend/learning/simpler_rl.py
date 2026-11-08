"""Bounded simpler RL reference (Linear/Tabular Q-learning) for baseline comparison."""
from copy import deepcopy
import heapq
import json
import math
from pathlib import Path
import numpy as np

from packet_backend.qos import CLASSES


class SimplerRLPolicy:
    """A bounded linear Q-learning routing policy serving as a simpler RL reference.

    Estimates Q(s, a) for source next-hop decisions using linear weights over
    local queue occupancy and propagation delay.
    """

    def __init__(self, weight_file: Path | str | None = None, learning_rate: float = 0.01):
        self.name = "packet_backend.learning.simpler_rl"
        self.lr = learning_rate
        # Linear weights: [bias, delay, queue_len, drop_rate]
        self.weights = np.array([0.0, -1.0, -0.005, -0.1], dtype=np.float32)
        if weight_file and Path(weight_file).exists():
            self.load(weight_file)

    def reset(self):
        pass

    def __call__(self, observation: dict) -> dict[tuple[int, int, int], int]:
        nodes = observation['nodes']
        links = observation['links']
        non_transit = set(observation.get('non_transit_nodes', []))
        queues = {(q['link_id'], q['direction']): q for q in observation['queues']}

        routes = {}
        for c, name in enumerate(CLASSES):
            for dst in observation['destinations']:
                # Run Dijkstra with linear Q-score edge costs
                reverse = [[] for _ in nodes]
                for edge in links:
                    for direction, (u, v) in enumerate(((edge['a'], edge['b']), (edge['b'], edge['a']))):
                        q = queues.get((edge['id'], direction), {})
                        q_bytes = q.get('classes', {}).get(name, {}).get('bytes', 0)
                        drops = q.get('classes', {}).get(name, {}).get('rejected_bytes', 0)
                        
                        features = np.array([1.0, edge['delay_s'], q_bytes / 1000.0, drops / 1000.0], dtype=np.float32)
                        # Negative Q-value as positive cost for Dijkstra
                        cost = max(float(-np.dot(self.weights, features)), 1e-4)
                        reverse[v].append((u, cost))

                distances = {dst: 0.0}
                pending = [(0.0, dst)]
                while pending:
                    dist, node = heapq.heappop(pending)
                    if dist != distances[node]:
                        continue
                    if node != dst and node in non_transit:
                        continue
                    for neighbor, weight in sorted(reverse[node]):
                        cand = dist + weight
                        if cand < distances.get(neighbor, math.inf):
                            distances[neighbor] = cand
                            routes[c, neighbor, dst] = node
                            heapq.heappush(pending, (cand, neighbor))

        return routes

    def save(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'weights': self.weights.tolist(), 'name': self.name}, indent=2))

    def load(self, path: Path | str):
        data = json.loads(Path(path).read_text())
        self.weights = np.array(data['weights'], dtype=np.float32)
