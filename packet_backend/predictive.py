"""Class-specific predictive heuristics with consistent destination trees and fallbacks."""
from copy import deepcopy
import heapq
import math

from packet_backend.prediction import QueueForecaster, unknown_links
from packet_backend.qos import CLASSES

MODES = ('qos_current', 'lifetime', 'queue_forecast', 'predictive')


def tree(nodes, destination, edges, cost):
    reverse = [[] for _ in nodes]
    for edge in edges:
        for direction, (a, b) in enumerate(((edge['a'], edge['b']), (edge['b'], edge['a']))):
            weight = cost(edge, direction, a, b)
            if weight is not None:
                reverse[b].append((a, weight))
    distances, routes = {destination: 0.0}, {}
    pending = [(0.0, destination)]
    while pending:
        distance, node = heapq.heappop(pending)
        if distance != distances[node]:
            continue
        for neighbor, weight in sorted(reverse[node]):
            candidate = distance+weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                routes[neighbor, destination] = node
                heapq.heappush(pending, (candidate, neighbor))
    return routes


def path_edges(routes, source, destination, edge_pairs):
    path, seen = [], set()
    while source != destination:
        if source in seen or (source, destination) not in routes:
            return None
        seen.add(source)
        nxt = routes[source, destination]
        edge = edge_pairs.get((source, nxt))
        if edge is None:
            return None
        path.append(edge)
        source = nxt
    return path


class PredictivePolicy:
    def __init__(self, mode, config, orbital=None):
        if mode not in MODES:
            raise ValueError(f'Unknown predictive mode {mode}')
        self.mode, self.config, self.orbital = mode, deepcopy(config), orbital
        self.name = f'packet_backend.predictive.{mode}'
        self.reset()

    def reset(self):
        self.queues = QueueForecaster(self.config)
        self.previous = {}
        self.last_diagnostics = {}

    def __call__(self, obs):
        from packet_backend.controller import congestion_routes
        use_queue = self.mode in ('queue_forecast', 'predictive')
        use_links = self.mode in ('lifetime', 'predictive')
        queue_forecasts = self.queues.predict(obs)
        link_forecasts = self.orbital.predict(obs) if use_links and self.orbital else unknown_links(obs)
        queues = {(q['link_id'], q['direction']): q for q in queue_forecasts}
        links = {link['link_id']: link for link in link_forecasts}
        pairs = {}
        for edge in obs['links']:
            pairs[edge['a'], edge['b']] = edge, 0
            pairs[edge['b'], edge['a']] = edge, 1
        baseline = congestion_routes(obs)
        output, decisions, fallbacks = {}, [], []
        weights = obs['qos']['weights']
        next_queue = {(q['link_id'], q['direction']): q for q in obs['queues']}
        all_bulk = sum(flow['flow_type']=='BULK' for flow in obs['active_flows']) or 1
        for c, name in enumerate(CLASSES):
            targets = obs['qos']['targets'][name]
            for dst in obs['destinations']:
                demands = [f for f in obs['active_flows'] if f['class_id']==c and f['dst']==dst]
                payload = max((f['size'] for f in demands), default=(128, 800, 1200)[c])
                wire = payload + (60 if any(f['protocol']=='tcp' for f in demands) else 30)
                deadline = min((f['deadline_s'] for f in demands if f['deadline_s'] is not None), default=targets.get('deadline_s'))
                minimum = max((f['min_goodput_bps'] or 0 for f in demands), default=targets.get('min_goodput_bps', 0))
                budget = deadline or self.config['queue_horizon_s']

                def delay(edge, direction, forecast=True):
                    q = queues[edge['id'], direction]['classes'][name]
                    size = q['predicted_bytes'] if use_queue and forecast else q['current_bytes']
                    service = max(q['nominal_share_bytes_s'], q['expected_service_bytes_s'])
                    prop = links[edge['id']]['predicted_delay_s'] if use_links and forecast else edge['delay_s']
                    # One observed competing packet can already be serializing.
                    observed = next_queue[edge['id'], direction]['classes']
                    blocking = max((v['bytes']/v['packets'] for n, v in observed.items() if n!=name and v['packets']), default=0)
                    return max(prop, edge['delay_s']) + size/service + (wire+blocking)*8/edge['capacity_bps']


                def preferred_cost(edge, direction, a, b, penalty=True):
                    lifetime = links[edge['id']]['lifetime_lower_s']
                    if use_links and lifetime is not None and lifetime <= budget+self.config['link_guard_s']:
                        return None
                    share = edge['capacity_bps']*weights[name]/sum(weights.values())
                    if name=='BULK' and share/all_bulk < minimum:
                        return None
                    value = delay(edge, direction)
                    old = self.previous.get((c, a, dst))
                    if penalty and old is not None and old != b:
                        value += self.config['change_penalty_s']
                    return value

                selected = tree(obs['nodes'], dst, obs['links'], preferred_cost)

                def violations(routes):
                    reasons = set()
                    for flow in demands:
                        path = path_edges(routes, flow['src'], dst, pairs)
                        if path is None:
                            reasons.add('no_preferred_path')
                            continue
                        estimate = sum(delay(edge, direction) for edge, direction in path)
                        limit = flow['deadline_s']
                        if limit is not None and estimate > limit:
                            reasons.add('predicted_deadline_violation')
                        if use_links and any(links[e['id']]['lifetime_lower_s'] is not None and
                                             links[e['id']]['lifetime_lower_s'] <= estimate+self.config['link_guard_s'] for e, _ in path):
                            reasons.add('insufficient_link_lifetime')
                    return sorted(reasons)

                reasons = violations(selected)
                if reasons:
                    # Deadline/lifetime safeguards override the switching penalty.
                    selected = tree(obs['nodes'], dst, obs['links'], lambda e, d, a, b: preferred_cost(e, d, a, b, False))
                    reasons = violations(selected)
                if self.mode=='lifetime' and self.orbital is None:
                    reasons = ['link_forecast_unavailable']
                fallback = bool(reasons)
                if fallback:
                    # Replace the entire destination tree, never splice incompatible trees.
                    selected = {key: nxt for key, nxt in baseline.items() if key[1]==dst}
                    if demands:
                        fallbacks.append({'time_s': obs['time_s'], 'flow_type': name, 'destination': dst, 'reasons': reasons})
                output.update({(c, src, target): nxt for (src, target), nxt in selected.items()})
                for flow in demands:
                    path = path_edges(selected, flow['src'], dst, pairs)
                    estimate = sum(delay(e, d, not fallback) for e, d in path) if path is not None else None
                    share = min((e['capacity_bps']*weights[name]/sum(weights.values())/all_bulk for e, _ in path), default=0) if path is not None else 0
                    decisions.append({'flow_id': flow['id'], 'flow_type': name,
                                      'estimated_delay_s': estimate, 'deadline_s': flow['deadline_s'],
                                      'deadline_at_risk': flow['deadline_s'] is not None and (estimate is None or estimate>flow['deadline_s']),
                                      'bulk_nominal_share_bps': share if name=='BULK' else None,
                                      'bulk_floor_at_risk': name=='BULK' and share<(flow['min_goodput_bps'] or 0),
                                      'fallback': fallback, 'unreachable': path is None,
                                      'path': [flow['src'], *[e['b'] if d==0 else e['a'] for e, d in path]] if path is not None else []})
        self.previous = dict(output)
        self.last_diagnostics = {'mode': self.mode, 'queue_forecasts': queue_forecasts,
                                 'link_forecasts': link_forecasts, 'decisions': decisions, 'fallbacks': fallbacks}
        return output
