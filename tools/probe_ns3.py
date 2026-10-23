"""Optional ns-3 compatibility exercise. Run in its own pinned virtual environment."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import cppyy
from ns import ns

cppyy.cppdef(Path(__file__).with_suffix('.cc').read_text())


def exercise(delays, count=1, interval=0.1, feedback=False):
    probe = cppyy.gbl.leo_probe.Probe()
    times = cppyy.gbl.std.vector['double'](delays)
    probe.Setup(times, count, interval)
    observed = []
    for stop in [0.012, 0.03, 0.06, 1.0]:
        ns.Simulator.Stop(ns.Seconds(stop - ns.Simulator.Now().GetSeconds()))
        ns.Simulator.Run()
        observed.append({'time_s': ns.Simulator.Now().GetSeconds(), 'queue_packets': int(probe.QueuePackets()),
                         'received': int(probe.received)})
        if feedback and stop in (0.03, 0.06):
            probe.SetRouteEnabled(stop == 0.06)
    result = {'received': int(probe.received), 'queue_drops': int(probe.dropped),
              'attempted': int(probe.attempted), 'send_failures': int(probe.sendFailures),
              'first_rx_s': float(probe.firstRx), 'observations': observed}
    ns.Simulator.Destroy()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='runs/baseline/results.json')
    parser.add_argument('--output', default='runs/ns3-probe.json')
    args = parser.parse_args()
    single = exercise([0.005])
    expected = 0.01 + 1030 * 8 / 1e6 + 0.005  # payload + UDP/IP/PPP serialization
    assert single['received'] == 1 and abs(single['first_rx_s'] - expected) < 1e-8, single
    saturated = exercise([0.005], count=100, interval=0.001)
    controlled = exercise([0.005], count=100, interval=0.001, feedback=True)
    assert saturated['queue_drops'] > 0
    assert controlled['observations'][0]['queue_packets'] > 0
    assert controlled['send_failures'] > 0
    assert controlled['received'] < saturated['received']
    assert controlled['observations'][-1]['received'] > controlled['observations'][2]['received']
    baseline = json.loads(Path(args.baseline).read_text())
    path = baseline['route_samples'][0]['target_path']
    timestamp = baseline['route_samples'][0]['time']
    snapshot = next(s for s in baseline['topology'] if s['time_s'] == timestamp)
    distances = {frozenset((e['a'], e['b'])): e['distance_km'] for e in snapshot['links']}
    delays = [distances[frozenset((a,b))] / 299792.458 for a,b in zip(path,path[1:])]
    matched = exercise(delays)
    expected_chain = 0.01 + sum(delays) + len(delays) * 1030 * 8 / 1e6
    assert matched['received'] == 1 and abs(matched['first_rx_s'] - expected_chain) < 1e-7, matched
    output = {'ns3_version': importlib.metadata.version('ns3'), 'single_link': single,
              'single_expected_rx_s': expected, 'saturated': saturated, 'controlled': controlled,
              'matched_path': path, 'matched_delays_s': delays, 'matched_chain': matched,
              'matched_expected_rx_s': expected_chain,
              'scope': 'UDP static route-chain only; not full dynamic constellation or TCP validation'}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    main()
