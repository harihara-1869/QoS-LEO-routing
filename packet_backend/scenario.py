"""Validate and export named scenarios to a deterministic numeric ns-3 plan."""
from copy import deepcopy
import json
import math
from pathlib import Path

C_KM_S = 299792.458


def positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{name} must be finite and {"nonnegative" if zero else "positive"}')
    return value


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in [{low}, {high}]')
    return value


def prepare(config: dict, output: Path) -> dict:
    """Accept explicit dynamic graphs or generate snapshots from the existing orbital model."""
    config = deepcopy(config)
    if config.get('schema_version') != 1:
        raise ValueError('Unsupported schema_version')
    duration = positive(config['duration_s'], 'duration_s')
    seed = integer(config.get('seed', 7), 'seed', 1, 2**32-1)
    network = config.get('network', {})
    rate = integer(network.get('capacity_bps', 10000000), 'capacity_bps', 1, 10**12)
    queue = integer(network.get('queue_packets', 100), 'queue_packets', 1, 1000000)
    mtu = integer(network.get('mtu_bytes', 9000), 'mtu_bytes', 576, 65535)
    ttl = integer(network.get('ttl', 32), 'ttl', 1, 255)
    explicit = 'topology' in config
    if explicit:
        names = config['topology']['nodes']
        raw_snapshots = config['topology']['snapshots']
    else:
        from setup import generate_omm_csv, get_satellite_data
        from logic_module import LogicalConfig
        from sim_man import SimulationManager
        step = positive(config['step_s'], 'step_s')
        generate_omm_csv(str(output / 'constellation.csv'), **config['constellation'], epoch=config['epoch'])
        satellites = get_satellite_data(csv_file=str(output / 'constellation.csv'))
        sim = SimulationManager(satellites, config['epoch'], LogicalConfig(**config['links']), config['ground_stations'])
        for tick in range(math.ceil(duration / step)):
            sim.core.current_time = tick * step
            sim.update_topology()
        raw_snapshots = sim.snapshots
        names = raw_snapshots[0]['nodes']
    if not names or len(names) > 65534 or any(not isinstance(n, str) or not n for n in names) or len(names) != len(set(names)):
        raise ValueError('Node names must be nonempty, unique strings (at most 65534)')
    node_ids = {name: i for i, name in enumerate(names)}
    if not raw_snapshots or raw_snapshots[0]['time_s'] != 0:
        raise ValueError('Topology must start with a snapshot at time 0')
    links_by_pair = {}
    snapshots = []
    previous = -1
    for snap in raw_snapshots:
        time = positive(snap['time_s'], 'snapshot time', zero=True)
        if not previous < time < duration:
            raise ValueError('Snapshot times must strictly increase within [0, duration)')
        previous = time
        states = {}
        for edge in snap['links']:
            if edge['a'] not in node_ids or edge['b'] not in node_ids or edge['a'] == edge['b']:
                raise ValueError('Links require distinct known nodes')
            pair = tuple(sorted((node_ids[edge['a']], node_ids[edge['b']])))
            if pair in states:
                raise ValueError('Parallel links are not supported; use one physical link per node pair')
            delay = edge.get('delay_s')
            if delay is None:
                delay = positive(edge['distance_km'], 'distance_km') / C_KM_S
            delay = positive(delay, 'delay_s')
            edge_rate = integer(edge.get('capacity_bps', rate), 'link capacity', 1, 10**12)
            edge_queue = integer(edge.get('queue_packets', queue), 'link queue', 1, 1000000)
            settings = (edge_rate, edge_queue)
            if pair in links_by_pair and links_by_pair[pair] != settings:
                raise ValueError('Capacity/queue settings must be constant per physical link')
            links_by_pair[pair] = settings
            states[pair] = delay
        snapshots.append({'time_s': time, 'states': states})
    pairs = sorted(links_by_pair)
    if len(pairs) > 100000:
        raise ValueError('Scenario exceeds the bounded adapter link limit')
    link_ids = {pair: i for i, pair in enumerate(pairs)}
    links = [{'id': i, 'a': a, 'b': b, 'capacity_bps': links_by_pair[(a,b)][0],
              'queue_packets': links_by_pair[(a,b)][1]} for i, (a,b) in enumerate(pairs)]
    for snap in snapshots:
        snap['links'] = [{'id': link_ids[pair], 'delay_s': delay} for pair, delay in sorted(snap.pop('states').items())]
    flows = []
    ids = set()
    for item in config['flows']:
        f = dict(item)
        fid = integer(f['flow_id'], 'flow_id', 0, 2**32-1)
        if fid in ids:
            raise ValueError('Flow IDs must be unique')
        ids.add(fid)
        if f['src'] not in node_ids or f['dst'] not in node_ids or f['src'] == f['dst']:
            raise ValueError('Flows require distinct known endpoints')
        protocol = f.get('protocol', 'udp').lower()
        if protocol not in ('udp', 'tcp'):
            raise ValueError('protocol must be udp or tcp')
        start = positive(f['start_time'], 'flow start', zero=True)
        end = positive(f['end_time'], 'flow end')
        if not start < min(end, duration):
            raise ValueError('Flow must start before its end and the run horizon')
        size = integer(f.get('packet_size_bytes', 1000), 'payload/segment size', 1, mtu - (60 if protocol == 'tcp' else 28))
        flow_rate = positive(f.get('data_rate_bps', 0), 'flow rate', zero=True)
        if protocol == 'udp' and flow_rate and size*8/flow_rate < 1e-9:
            raise ValueError('UDP interval is below the ns-3 nanosecond clock resolution')
        max_bytes = integer(f.get('max_bytes', 0), 'max_bytes', 1 if protocol=='tcp' else 0, 2**40)
        if protocol == 'tcp' and flow_rate:
            raise ValueError('TCP is a finite bulk transfer; omit data_rate_bps (Reno controls its rate)')
        flows.append({'id': fid, 'src': node_ids[f['src']], 'dst': node_ids[f['dst']], 'protocol': protocol,
                      'start': start, 'end': end, 'rate': flow_rate, 'size': size, 'max_bytes': max_bytes})
    if len(flows) > 56000:
        raise ValueError('Too many flows for per-flow destination ports')
    plan = {'duration_s': duration, 'seed': seed, 'mtu_bytes': mtu, 'ttl': ttl,
            'nodes': names, 'links': links, 'snapshots': snapshots, 'flows': flows,
            'topology_source': 'explicit' if explicit else 'skyfield_sgp4',
            'source_scenario': config}
    lines = [f'LEO2 {len(names)} {len(links)} {len(flows)} {len(snapshots)} {duration} {seed} {mtu} {ttl}']
    lines += [f'{l["a"]} {l["b"]} {l["capacity_bps"]} {l["queue_packets"]}' for l in links]
    lines += [' '.join(str(f[key]) for key in ('id','src','dst','protocol','start','end','rate','size','max_bytes')) for f in flows]
    for snap in snapshots:
        lines.append(f'{snap["time_s"]} {len(snap["links"])}')
        lines += [f'{l["id"]} {l["delay_s"]:.17g}' for l in snap['links']]
    (output / 'engine.plan').write_text('\n'.join(lines)+'\n')
    (output / 'prepared.json').write_text(json.dumps(plan, indent=2, allow_nan=False)+'\n')
    return plan
