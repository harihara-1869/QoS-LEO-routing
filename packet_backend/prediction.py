"""Causal queue forecasts and model-based orbital forecasts, without learned weights."""
from collections import OrderedDict
from copy import deepcopy
import math

from packet_backend.qos import CLASSES, number

DEFAULTS = {
    'queue_horizon_s': 0.1,
    'orbital_horizon_s': 15.0,
    'orbital_step_s': 5.0,
    'ewma_alpha': 0.5,
    'link_guard_s': 0.1,
    'change_penalty_s': 0.005,
}


def settings(config=None):
    if config is None:
        config = {}
    if not isinstance(config, dict) or set(config) - set(DEFAULTS):
        raise ValueError('Unknown prediction configuration fields')
    result = {**DEFAULTS, **config}
    for key, value in result.items():
        if key in ('link_guard_s', 'change_penalty_s') and value == 0 and not isinstance(value, bool):
            continue
        number(value, key)
    if result['ewma_alpha'] > 1:
        raise ValueError('ewma_alpha must be in (0, 1]')
    if result['orbital_step_s'] > result['orbital_horizon_s']:
        raise ValueError('orbital_step_s must not exceed orbital_horizon_s')
    if result['orbital_horizon_s']/result['orbital_step_s'] > 100:
        raise ValueError('At most 100 orbital forecast steps are supported')
    if min(result['queue_horizon_s'], result['orbital_step_s']) < 1e-6:
        raise ValueError('Forecast steps must be at least one microsecond')
    return result


class QueueForecaster:
    """EWMA of observed offered arrivals/service; no future flow schedule access."""

    def __init__(self, config):
        self.config = config
        self.history = {}

    def predict(self, observation):
        now = observation['time_s']
        horizon = self.config['queue_horizon_s']
        alpha = self.config['ewma_alpha']
        edges = {edge['id']: edge for edge in observation['links']}
        active_keys = {(q['link_id'], q['direction']) for q in observation['queues'] if q['link_id'] in edges}
        # Inactive links invalidate trend history. A restored link starts cold.
        self.history = {key: value for key, value in self.history.items() if key in active_keys}
        result = []
        weights = observation['qos']['weights']
        for queue in observation['queues']:
            key = queue['link_id'], queue['direction']
            if key not in active_keys:
                continue
            edge = edges[key[0]]
            previous = self.history.get(key)
            elapsed = now - previous['time_s'] if previous else 0
            arrivals, services = {}, {}
            for name in CLASSES:
                current = queue['classes'][name]
                if elapsed > 0:
                    old = previous['classes'][name]
                    arrivals[name] = alpha * max(0, current['arrived_bytes']-old['arrived_bytes'])/elapsed + (1-alpha)*previous['arrivals'][name]
                    services[name] = alpha * max(0, current['served_bytes']-old['served_bytes'])/elapsed + (1-alpha)*previous['services'][name]
                else:
                    arrivals[name] = services[name] = 0.0
            active = [name for name in CLASSES if queue['classes'][name]['bytes'] or arrivals[name] > 0]
            capacity = edge['capacity_bps']/8
            active_weight = sum(weights[name] for name in active) or sum(weights.values())
            expected = {name: max(services[name], capacity*weights[name]/active_weight) if name in active else 0.0 for name in CLASSES}
            total = sum(expected.values())
            if total > capacity:
                expected = {name: value*capacity/total for name, value in expected.items()}
            forecasts = {}
            for c, name in enumerate(CLASSES):
                current = queue['classes'][name]
                slots = edge['queue_packets']//3 if c < 2 else edge['queue_packets']-2*(edge['queue_packets']//3)
                buffer_bound = slots*(observation['mtu_bytes']+2)
                raw = current['bytes'] + (arrivals[name]-expected[name])*horizon
                # Warm-up uses persistence; an idle measured service rate is not capacity.
                predicted = min(buffer_bound, max(0.0, raw)) if elapsed > 0 else float(current['bytes'])
                forecasts[name] = {
                    'current_bytes': current['bytes'], 'predicted_bytes': predicted,
                    'arrival_bytes_s': arrivals[name], 'measured_service_bytes_s': services[name],
                    'expected_service_bytes_s': expected[name],
                    'nominal_share_bytes_s': capacity*weights[name]/sum(weights.values()),
                    'overflow_pressure_bytes': max(0.0, raw-buffer_bound),
                }
            result.append({'link_id': key[0], 'direction': key[1], 'at_s': now+horizon,
                           'warmup': elapsed <= 0, 'classes': forecasts})
            self.history[key] = {'time_s': now, 'classes': deepcopy(queue['classes']),
                                 'arrivals': arrivals, 'services': services}
        return result


class OrbitalForecaster:
    """Recompute the public orbital model; never reads exported future snapshots."""

    def __init__(self, satellites, epoch, link_config, ground_stations, config, *, orbital_start_s=0.0, topology_step_s=None):
        from constellation.topology import LogicalConfig
        from constellation.snapshots import TopologySnapshots
        self.model = TopologySnapshots(satellites, epoch, LogicalConfig(**link_config), ground_stations, orbital_start_s)
        self.config = config
        self.cache = OrderedDict()
        self.topology_step_s = topology_step_s or config['orbital_step_s']
        self.last_tick = -1
        self._satellites, self._links, self._ground = satellites, link_config, ground_stations

    def geometry(self, seconds):
        # Replay known terminal state on the physical update grid. Future queries
        # advance this independent model; cached past states never rewind it.
        tick = math.floor((seconds+1e-8)/self.topology_step_s)
        if tick in self.cache:
            return self.cache[tick]
        if tick < self.last_tick:
            from constellation.topology import LogicalTopology, LogicalConfig
            self.model.topology = LogicalTopology(self._satellites,LogicalConfig(**self._links),self._ground)
            self.last_tick = max([k for k in self.cache if k <= tick], default=-1)
        while self.last_tick < tick:
            self.last_tick += 1
            t = self.model.get_sim_time(self.last_tick*self.topology_step_s)
            topology = self.model.topology
            positions, _, _, _ = topology.compute(t)
            ground = {name:topology.get_gs_position(name,t) for name,*_ in topology.ground_stations}
            graph = topology.construct_unified_graph(positions,ground)
            names = graph.vs['name']
            self.cache[self.last_tick] = {tuple(sorted((names[e.source],names[e.target]))):float(e['weight'])/299792.458 for e in graph.es}
            while len(self.cache)>256:
                self.cache.popitem(last=False)
        return self.cache[tick]

    def predict(self, observation):
        now = observation['time_s']
        horizon, step = self.config['orbital_horizon_s'], self.config['orbital_step_s']
        offsets = sorted({0.0, horizon, *[min(i*step, horizon) for i in range(1, math.ceil(horizon/step)+1)]})
        states = [(offset, self.geometry(now+offset)) for offset in offsets]
        result = []
        for edge in observation['links']:
            pair = tuple(sorted((observation['nodes'][edge['a']], observation['nodes'][edge['b']])))
            samples = [{'at_s': now+offset, 'available': pair in state, 'delay_s': state.get(pair)} for offset, state in states]
            lower, upper = horizon, None
            for i, sample in enumerate(samples):
                if not sample['available']:
                    lower = offsets[max(0, i-1)]
                    upper = offsets[i]
                    break
            future_delay = next((sample['delay_s'] for sample in samples[1:] if sample['available']), edge['delay_s'])
            result.append({'link_id': edge['id'], 'source': 'orbital_model',
                           'lifetime_lower_s': lower, 'lifetime_upper_s': upper,
                           'censored': upper is None, 'predicted_delay_s': future_delay, 'samples': samples})
        return result


def unknown_links(observation):
    return [{'link_id': edge['id'], 'source': 'unavailable_for_explicit_graph',
             'lifetime_lower_s': None, 'lifetime_upper_s': None, 'censored': True,
             'predicted_delay_s': edge['delay_s'], 'samples': []} for edge in observation['links']]
