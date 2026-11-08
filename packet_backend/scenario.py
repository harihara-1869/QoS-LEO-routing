"""Validate and export named scenarios to a deterministic numeric ns-3 plan."""
from copy import deepcopy
import json
import math
from pathlib import Path

from packet_backend.prediction import settings as prediction_settings
from packet_backend.qos import CLASSES, classify, normalize

C_KM_S = 299792.458


def positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{name} must be finite and {"nonnegative" if zero else "positive"}')
    return value


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in [{low}, {high}]')
    return value


def prepare(config: dict, output: Path, *, class_routing=False) -> dict:
    """Accept explicit dynamic graphs or generate snapshots from the existing orbital model."""
    config = deepcopy(config)
    if not isinstance(config.get('record_control_details',True),bool):
        raise ValueError('record_control_details must be boolean')
    qos = normalize(config.get('qos'))
    if not isinstance(config.get('allow_ground_transit',True), bool):
        raise ValueError('allow_ground_transit must be boolean')
    prediction = prediction_settings(config.get('prediction')) if class_routing else None
    if class_routing and qos is None:
        raise ValueError('Predictive/class routing requires an explicit qos configuration')
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
        from constellation.omm import generate_omm_csv, get_satellite_data
        from constellation.topology import LogicalConfig
        from constellation.snapshots import TopologySnapshots
        step = positive(config['step_s'], 'step_s')
        csv_file = output / 'constellation.csv'
        if not csv_file.exists():
            generate_omm_csv(str(csv_file), **config['constellation'], epoch=config['epoch'])
        satellites = get_satellite_data(csv_file=str(csv_file))
        orbital_start = positive(config.get('orbital_start_s',0), 'orbital_start_s', zero=True)
        sim = TopologySnapshots(satellites, config['epoch'], LogicalConfig(**config['links']), config['ground_stations'], orbital_start)
        for tick in range(math.ceil(duration / step)):
            sim.update_topology(tick * step)
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
            delay = float(positive(delay, 'delay_s'))
            edge_rate = integer(edge.get('capacity_bps', rate), 'link capacity', 1, 10**12)
            edge_queue = integer(edge.get('queue_packets', queue), 'link queue', 1, 1000000)
            if qos and edge_queue < 3:
                raise ValueError('QoS needs at least three queue slots per direction')
            settings = (edge_rate, edge_queue)
            if pair in links_by_pair and links_by_pair[pair] != settings:
                raise ValueError('Capacity/queue settings must be constant per physical link')
            links_by_pair[pair] = settings
            states[pair] = delay
        snapshots.append({'time_s': time, 'states': states})
    control_step = config.get('control_interval_s')
    if control_step is not None:
        positive(control_step, 'control_interval_s')
        if control_step < 1e-6:
            raise ValueError('control_interval_s must be at least one microsecond')
        # Merge in ns-3 clock units: 0.3 and 3*0.1 are the same event time.
        times_by_ns = {round(tick*control_step*1e9): tick*control_step
                       for tick in range(math.ceil(duration/control_step))
                       if tick*control_step < duration}
        times_by_ns.update({round(s['time_s']*1e9): s['time_s'] for s in snapshots})
        times = sorted(times_by_ns.values())
        expanded, index = [], 0
        for time in times:
            while index+1 < len(snapshots) and snapshots[index+1]['time_s'] <= time:
                index += 1
            expanded.append({'time_s': time, 'states': dict(snapshots[index]['states'])})
        snapshots = expanded
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
        service = classify(f, qos)
        if protocol == 'tcp' and (service['flow_type'] != 'BULK' or service['deadline_s'] is not None):
            raise ValueError('TCP is Bulk byte-stream traffic; urgent deadlines apply to UDP datagrams')
        flows.append({**service, 'id': fid, 'src': node_ids[f['src']], 'dst': node_ids[f['dst']], 'protocol': protocol,
                      'start': start, 'end': end, 'rate': flow_rate, 'size': size, 'max_bytes': max_bytes})
    if len(flows) > 56000:
        raise ValueError('Too many flows for per-flow destination ports')
    plan = {'duration_s': duration, 'seed': seed, 'mtu_bytes': mtu, 'ttl': ttl,
            'nodes': names, 'links': links, 'snapshots': snapshots, 'flows': flows, 'qos': qos,
            'class_routing': class_routing, 'prediction': prediction,
            'allow_ground_transit': config.get('allow_ground_transit', True),
            'record_control_details': config.get('record_control_details',True),
            'topology_source': 'explicit' if explicit else 'skyfield_sgp4',
            'source_scenario': config}
    weights = [qos['weights'][name] for name in CLASSES] if qos else [4, 2, 1]
    quantum = qos['quantum_bytes'] if qos else 1500
    lines = [f'LEO4 {len(names)} {len(links)} {len(flows)} {len(snapshots)} {duration} {seed} {mtu} {ttl} {int(qos is not None)} ' + ' '.join(map(str, [*weights, quantum, int(class_routing)]))]
    lines += [f'{l["a"]} {l["b"]} {l["capacity_bps"]} {l["queue_packets"]}' for l in links]
    lines += [' '.join(str(f[key]) for key in ('id','src','dst','protocol','start','end','rate','size','max_bytes','class_id')) for f in flows]
    for snap in snapshots:
        lines.append(f'{snap["time_s"]} {len(snap["links"])}')
        lines += [f'{l["id"]} {l["delay_s"]:.17g}' for l in snap['links']]
    (output / 'engine.plan').write_text('\n'.join(lines)+'\n')
    (output / 'prepared.json').write_text(json.dumps(plan, indent=2, allow_nan=False)+'\n')
    return plan
