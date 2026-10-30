"""Current-state routing and the synchronous observation/action protocol."""
from copy import deepcopy
import heapq
import json
from pathlib import Path
from queue import Queue, Empty
import subprocess
from threading import Thread
import time


def _dijkstra(observation, congestion=False):
    # Reverse adjacency: cost stored at b is the cost of the directed a -> b edge.
    reverse = [[] for _ in observation['nodes']]
    queues = {(q['link_id'], q['direction']): q['bytes'] for q in observation['queues']}
    for edge in observation['links']:
        a, b, delay = edge['a'], edge['b'], edge['delay_s']
        forward = delay + (queues.get((edge['id'], 0), 0)*8/edge['capacity_bps'] if congestion else 0)
        backward = delay + (queues.get((edge['id'], 1), 0)*8/edge['capacity_bps'] if congestion else 0)
        reverse[b].append((a, forward))
        reverse[a].append((b, backward))
    routes = {}
    for destination in observation['destinations']:
        distance = {destination: 0.0}
        pending = [(0.0, destination)]
        while pending:
            cost, node = heapq.heappop(pending)
            if cost != distance[node]:
                continue
            for neighbor, edge_cost in sorted(reverse[node]):
                candidate = cost + edge_cost
                if candidate < distance.get(neighbor, float('inf')):
                    distance[neighbor] = candidate
                    routes[neighbor, destination] = node
                    heapq.heappush(pending, (candidate, neighbor))
    return routes


def shortest_routes(observation: dict) -> dict[tuple[int, int], int]:
    """Propagation-weighted Dijkstra with stable tie breaking."""
    return _dijkstra(observation)


def congestion_routes(observation: dict) -> dict[tuple[int, int], int]:
    """Current propagation + directed queued wire bytes / link capacity."""
    return _dijkstra(observation, congestion=True)


POLICIES = {'propagation': shortest_routes, 'congestion': congestion_routes}


def policy_name(policy):
    return getattr(policy, "name", f"{policy.__module__}.{getattr(policy, '__qualname__', type(policy).__qualname__)}")


def resolve_policy(policy, plan=None, output=None):
    if callable(policy):
        return policy
    from packet_backend.predictive import MODES, PredictivePolicy
    if policy in MODES:
        from packet_backend.prediction import OrbitalForecaster
        orbital = None
        if plan['topology_source'] == 'skyfield_sgp4' and policy in ('lifetime', 'predictive'):
            from setup import get_satellite_data
            source = plan['source_scenario']
            orbital = OrbitalForecaster(get_satellite_data(csv_file=output/'constellation.csv'), source['epoch'],
                                        source['links'], source['ground_stations'], plan['prediction'])
        return PredictivePolicy(policy, plan['prediction'], orbital)
    if policy not in POLICIES:
        raise ValueError(f'Unknown routing policy: {policy}')
    return POLICIES[policy]


def validate_routes(routes: dict, observation: dict) -> None:
    """Reject unavailable edges, duplicate/unknown endpoints, dead ends and cycles."""
    if any(len(key)==3 for key in routes):
        if any(len(key)!=3 or key[0] not in (0,1,2) for key in routes):
            raise ValueError('Invalid or mixed class routing keys')
        for c in range(3):
            validate_routes({(src,dst):nxt for (kind,src,dst),nxt in routes.items() if kind==c}, observation)
        return
    edges = {frozenset((edge['a'], edge['b'])) for edge in observation['links']}
    nodes = set(range(len(observation['nodes'])))
    for (src, dst), nxt in routes.items():
        if src not in nodes or dst not in observation['destinations'] or nxt not in nodes or src == dst:
            raise ValueError('Policy returned invalid routing endpoints')
        if frozenset((src, nxt)) not in edges:
            raise ValueError('Policy selected an unavailable link')
        seen = {src}
        current = nxt
        while current != dst:
            if current in seen:
                raise ValueError('Policy created a forwarding loop')
            seen.add(current)
            if (current, dst) not in routes:
                raise ValueError('Policy created a forwarding dead end')
            current = routes[current, dst]


def execute(binary: Path, plan: dict, output: Path, policy=shortest_routes, timeout_s=120) -> dict:
    if hasattr(policy, 'reset'):
        policy.reset()
    destinations = sorted({f['dst'] for f in plan['flows']} | {f['src'] for f in plan['flows'] if f['protocol']=='tcp'})
    inbox = Queue()
    def reader(stream):
        for line in stream:
            inbox.put(line)
        inbox.put(None)
    def read():
        try:
            line = inbox.get(timeout=timeout_s)
        except Empty as exc:
            raise TimeoutError('ns-3 observation timed out') from exc
        if line is None:
            raise RuntimeError(f'ns-3 exited before completing its protocol; see {output / "engine.stderr"}')
        return line.strip()
    records = []
    control_seconds = 0.0
    with (output / 'engine.stderr').open('w') as errors:
        process = subprocess.Popen([str(binary), str(output/'engine.plan'), str(output)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, bufsize=1)
        thread = Thread(target=reader, args=(process.stdout,), daemon=True)
        thread.start()
        try:
            for snapshot in plan['snapshots']:
                header = read().split()
                if len(header)!=3 or header[0]!='STATE' or abs(float(header[1])-snapshot['time_s'])>1e-8:
                    raise RuntimeError(f'Unexpected engine observation: {header}')
                if int(header[2]) != len(plan['links'])*2:
                    raise RuntimeError('Engine queue observation count mismatch')
                queues = []
                for _ in range(int(header[2])):
                    row = list(map(int, read().split()))
                    link, direction, packets, size = row[:4]
                    queue = {'link_id':link,'direction':direction,'packets':packets,'bytes':size}
                    if plan['qos']:
                        if len(row) != 19:
                            raise RuntimeError('Missing class queue observation')
                        queue['classes'] = {name: {'packets':row[4+2*i], 'bytes':row[5+2*i]}
                                            for i, name in enumerate(('CONTROL','REALTIME','BULK'))}
                        for i, name in enumerate(('CONTROL','REALTIME','BULK')):
                            queue['classes'][name].update(zip(('arrived_bytes','served_bytes','rejected_bytes'), row[10+3*i:13+3*i]))
                    queues.append(queue)
                if read()!='END':
                    raise RuntimeError('Invalid observation terminator')
                links = [{**plan['links'][edge['id']], 'delay_s':edge['delay_s']} for edge in snapshot['links']]
                observation = {'time_s':float(header[1]), 'nodes':list(plan['nodes']), 'links':links,
                               'queues':queues, 'destinations':destinations, 'qos':plan['qos']}
                if plan['class_routing']:
                    observation['mtu_bytes'] = plan['mtu_bytes']
                    observation['active_flows'] = [{key:f[key] for key in ('id','src','dst','class_id','flow_type','protocol','size','deadline_s','min_goodput_bps')}
                                                   for f in plan['flows'] if f['start'] <= observation['time_s'] < f['end']
                                                   and (f['protocol']=='tcp' or f['rate']>0)]
                start = time.perf_counter()
                routes = policy(observation)
                if plan['class_routing'] and all(len(key)==2 for key in routes):
                    routes = {(c,src,dst):nxt for c in range(3) for (src,dst),nxt in routes.items()}
                if not plan['class_routing'] and any(len(key)!=2 for key in routes):
                    raise ValueError('Class routing actions require prediction configuration')
                validate_routes(routes, observation)
                control_seconds += time.perf_counter()-start
                rows = [(*key,nxt) for key,nxt in sorted(routes.items())]
                process.stdin.write(f'ROUTES {len(rows)}\n'+''.join(' '.join(map(str,row))+'\n' for row in rows))
                process.stdin.flush()
                record = {**observation, 'routes':rows}
                if plan['class_routing']:
                    record['class_routes'] = rows
                    record['routes'] = [row[1:] for row in rows if row[0]==2]
                if hasattr(policy, 'last_diagnostics'):
                    record['prediction'] = deepcopy(policy.last_diagnostics)
                records.append(record)
            if read()!='DONE':
                raise RuntimeError('Engine did not finish cleanly')
            process.stdin.close()
            if process.wait(timeout=timeout_s):
                raise RuntimeError(f'ns-3 failed; see {output / "engine.stderr"}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            thread.join(timeout=5)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
    (output/'control.json').write_text(json.dumps(records,indent=2)+'\n')
    return {'observations':records, 'controller_wall_seconds':control_seconds}
