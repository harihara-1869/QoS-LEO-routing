"""Keep UDP datagram accounting separate from TCP byte-stream outcomes."""
from collections import Counter
import csv
import json
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    low = int(position)
    return ordered[low] + (ordered[min(low+1,len(ordered)-1)]-ordered[low])*(position-low)


def load_rows(path):
    with path.open() as file:
        return list(csv.DictReader(file, delimiter='\t'))


def route_path(routes, source, destination):
    mapping = {(a,b):n for a,b,n in routes}
    path = [source]
    while path[-1] != destination:
        nxt = mapping.get((path[-1],destination))
        if nxt is None:
            return []
        if nxt in path:
            raise ValueError('Loop in recorded routing state')
        path.append(nxt)
    return path


def summarize(plan: dict, output: Path, control: dict) -> dict:
    names = plan['nodes']
    duration = plan['duration_s']
    packets = []
    for row in load_rows(output/'udp.tsv'):
        packet = {key:int(row[key]) for key in ('packet_id','flow_id','size_bytes')}
        packet.update({key:float(row[key]) for key in ('created_s','ended_s')})
        packet.update(status=row['status'], reason=row['reason'], path=[names[int(i)] for i in row['path'].split(',')])
        packet['delay_s'] = packet['ended_s']-packet['created_s'] if packet['status']=='delivered' else None
        packets.append(packet)
    events = load_rows(output/'events.tsv')
    for event in events:
        event['time_s'] = float(event['time_s'])
        event['value'] = float(event['value'])
        for key in ('item','a','b'):
            event[key] = int(event[key])
    tcp = [{key:int(value) for key,value in row.items()} for row in load_rows(output/'tcp.tsv')]
    tcp_by_id = {f['flow_id']:f for f in tcp}
    flows = []
    for f in plan['flows']:
        route_changes = 0
        last_path = None
        for observation in control['observations']:
            rows = [row[1:] for row in observation['class_routes'] if row[0]==f['class_id']] if 'class_routes' in observation else observation['routes']
            path = route_path(rows, f['src'], f['dst'])
            if last_path is not None and last_path != path:
                route_changes += 1
            last_path = path
        summary = {'flow_id':f['id'], 'protocol':f['protocol'], 'src':names[f['src']], 'dst':names[f['dst']],
                   'route_changes':route_changes}
        if f['protocol']=='udp':
            subset = [p for p in packets if p['flow_id']==f['id']]
            counts = Counter(p['status'] for p in subset)
            delays = [p['delay_s'] for p in subset if p['status']=='delivered']
            delivered_bytes = sum(p['size_bytes'] for p in subset if p['status']=='delivered')
            summary.update(generated=len(subset), delivered=counts['delivered'], dropped=counts['dropped'],
                           in_flight=counts['in_flight'], delivered_bytes=delivered_bytes,
                           delivery_ratio=counts['delivered']/len(subset) if subset else None,
                           delay_mean_s=sum(delays)/len(delays) if delays else None,
                           delay_p95_s=percentile(delays,.95), delay_p99_s=percentile(delays,.99),
                           drop_reasons=dict(Counter(p['reason'] for p in subset if p['status']=='dropped')))
            if summary['generated'] != summary['delivered']+summary['dropped']+summary['in_flight']:
                raise ValueError('UDP accounting does not balance')
        else:
            summary.update(tcp_by_id[f['id']])
            summary['requested_bytes'] = f['max_bytes']
            summary['unaccepted_bytes'] = f['max_bytes']-summary['accepted_bytes']
            summary['outstanding_bytes'] = summary['accepted_bytes']-summary['delivered_bytes']
            summary['complete'] = summary['delivered_bytes']==f['max_bytes']
            summary['congestion_control'] = 'ns3::TcpLinuxReno'
            receptions = [e['time_s'] for e in events if e['kind']=='tcp_receive' and e['item']==f['id']]
            summary['first_delivery_s'] = receptions[0] if receptions else None
            summary['completion_s'] = receptions[-1] if summary['complete'] else None
            summary['completion_delay_s'] = summary['completion_s']-f['start'] if summary['complete'] else None
            if not 0 <= summary['delivered_bytes'] <= summary['accepted_bytes'] <= f['max_bytes']:
                raise ValueError('TCP byte accounting does not balance')
        summary['goodput_bps'] = summary['delivered_bytes']*8/duration
        flows.append(summary)
    queues = []
    for link in plan['links']:
        for direction in (0,1):
            selected = [e for e in events if e['kind']=='queue' and e['item']==link['id'] and e['a']==direction]
            count, previous, area, maximum = 0, 0.0, 0.0, 0
            for e in selected:
                area += count*(e['time_s']-previous)
                count, previous = int(e['value']), e['time_s']
                maximum = max(maximum,count)
            area += count*(duration-previous)
            queues.append({'link_id':link['id'],'direction':direction,'max_packets':maximum,
                           'mean_packets':area/duration,'packets_at_horizon':count})
    return {'schema_version':2,'backend':'ns-3.44','mode':'packet_simulation','duration_s':duration,
            'goodput_window':'entire_run','scenario':plan['source_scenario'], 'nodes':names,
            'flows':flows,'udp_packets':packets,'queues':queues,'events':events,
            'route_snapshots':[{'time_s':o['time_s'],'routes':o['routes'], **({'class_routes':o['class_routes']} if 'class_routes' in o else {})} for o in control['observations']],
            'assumptions':{'queue':'FIFO DropTail per directed device; flow control disabled; no root queue disc',
                           'link_down':'drop queued; invalidate all transmissions in progress; recompute routing',
                           'link_restore':'old invalidated transmissions remain invalid',
                           'clock':'ns-3 only; half-open run horizon [0,duration)',
                           'topology':'piecewise constant snapshots; propagation sampled at transmit start',
                           'transport':'UDP datagrams and finite TCP bulk streams; SACK disabled for Reno'}}
