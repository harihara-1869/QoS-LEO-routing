"""Seeded congested orbital scenarios for the learned-controller phase.

The link rates are an experimental stress scale, not operational measurements.
Two-terminal gateways compete for finite satellite ground beams. Short episodes
start near an attachment transition, with control ticks that resolve bursts.
"""
import math
import random

STATIONS = [['GS_INDIA', 28.6139, 77.209, 0],
            ['GS_USA', 37.7749, -122.4194, 0],
            ['GS_BRAZIL', -23.5505, -46.6333, 0],
            ['GS_AUSTRALIA', -33.8688, 151.2093, 0]]

CASES = ('normal', 'burst', 'overload')

# class, source, destination, offered Mbps at unit scale, payload bytes
BASE_FLOWS = [('CONTROL', 'GS_INDIA', 'GS_AUSTRALIA', 0.5, 128),
              ('REALTIME', 'GS_INDIA', 'GS_USA', 1.5, 800),
              ('BULK', 'GS_USA', 'GS_BRAZIL', 3.0, 1200),
              ('BULK', 'GS_BRAZIL', 'GS_AUSTRALIA', 3.0, 1200),
              ('BULK', 'GS_INDIA', 'GS_USA', 2.0, 1200)]

SCALE = {'normal': 1.0, 'burst': 0.6, 'overload': 1.9}


def orbital_workload(case, seed=7, duration=5.0):
    """Return a complete scenario configuration; pass it to run() or save as JSON."""
    if case not in CASES:
        raise ValueError(f'Unknown orbital workload {case}')
    if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not duration > 1.0:
        raise ValueError('Orbital workloads need a duration above one second')
    rng = random.Random(seed)
    flows = []

    def add(flow_type, src, dst, mbps, size, start=0.5, end=None):
        flows.append({'flow_id': len(flows) + 1, 'flow_type': flow_type, 'protocol': 'udp',
                      'src': src, 'dst': dst,
                      'start_time': round(start + rng.uniform(0, 0.002), 6),
                      'end_time': round(duration - 0.5 if end is None else end, 6),
                      'packet_size_bytes': size, 'data_rate_bps': int(mbps * 1e6)})

    for flow_type, src, dst, mbps, size in BASE_FLOWS:
        add(flow_type, src, dst, mbps * SCALE[case], size)
    if case == 'burst':
        for start in (duration*.3, duration*.6):
            add('CONTROL', 'GS_INDIA', 'GS_AUSTRALIA', 3.0, 128, start, min(start + .3, duration-.1))
            add('REALTIME', 'GS_INDIA', 'GS_USA', 4.0, 800, start, min(start + .3, duration-.1))

    return {'schema_version': 1, 'epoch': '2025-01-01T00:00:00+00:00', 'seed': seed,
            'duration_s': duration, 'orbital_start_s': 12.0, 'step_s': .1, 'control_interval_s': .05,
            'allow_ground_transit': False, 'record_control_details': False,
            'constellation': {'n_planes': 10, 'sats_per_plane': 20,
                              'inclination': 53, 'altitude_km': 550},
            'links': {'isl_max_km': 5000, 'min_elev_deg': 5, 'iol_cone_deg': 60,
                      'enable_iol': False, 'isl_capacity_bps': 10_000_000,
                      'ground_capacity_bps': 2_000_000, 'ground_links_per_station': 2,
                      'ground_beams_per_satellite': 2, 'isl_terminals_per_satellite': 4,
                      'ground_acquisition_s': .15, 'isl_acquisition_s': 1.0,
                      'ground_hysteresis_deg': .5, 'ground_min_dwell_s': .5,
                      'initial_links_ready': True},
            'ground_stations': [list(station) for station in STATIONS],
            'network': {'queue_packets': 40, 'mtu_bytes': 9000, 'ttl': 32},
            'qos': {}, 'flows': flows,
            # Class-specific routing with forecasts. Horizons stay inside the
            # run window and are aligned with the one-second control interval,
            # so both queue and link forecasts are scored rather than censored.
            'prediction': {'queue_horizon_s': .1, 'orbital_horizon_s': .5,
                           'orbital_step_s': .1, 'link_guard_s': .05}}
