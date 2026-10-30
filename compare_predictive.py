"""Matched Phase 4 heuristic/forecast comparisons with compact reproducibility evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from run_packet_scenario import run

POLICIES = ('propagation', 'congestion', 'qos_current', 'lifetime', 'queue_forecast', 'predictive')


def compare(scenario, output, policies=POLICIES):
    config = json.loads(Path(scenario).read_text()) if not isinstance(scenario, dict) else scenario
    if 'prediction' not in config:
        raise ValueError('Matched Phase 4 comparisons require prediction configuration for every policy')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'comparison.json').unlink(missing_ok=True)
    encoded = json.dumps(config, sort_keys=True, indent=2)+'\n'
    (output/'scenario.json').write_text(encoded)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    records = {}
    for policy in policies:
        result = run(config, output/policy, policy=policy)
        manifest = json.loads((output/policy/'manifest.json').read_text())
        records[policy] = {'scenario_sha256':digest, 'result_sha256':manifest['result_sha256'],
                           'classes':result['qos']['classes'],
                           'bulk_jain_active_goodput':result['qos']['bulk_jain_active_goodput'],
                           'bulk_service':result['qos']['bulk_service'],
                           'prediction':result['prediction'],
                           'route_changes':sum(flow['route_changes'] for flow in result['flows']),
                           'delivered':sum(flow.get('delivered',0) for flow in result['flows']),
                           'dropped':sum(flow.get('dropped',0) for flow in result['flows'])}
    summary = {'scenario_sha256':digest, 'policies':records,
               'source_sha256':manifest['source_sha256'], 'dependencies':manifest['dependencies'], 'ns3':manifest['ns3'],
               'comparison':'Identical scenario, scheduler, class routing support and control times. Only controller policy changes. Runtime measurements remain in individual manifests.'}
    (output/'comparison.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, help='Single scenario; otherwise run the checked-in Phase 4 suite')
    parser.add_argument('--output', type=Path, default=Path('runs/phase4'))
    parser.add_argument('--policies', nargs='+', choices=POLICIES, default=POLICIES)
    parser.add_argument('--evidence', type=Path, help='Optional compact suite evidence JSON')
    args = parser.parse_args()
    scenarios = [args.scenario] if args.scenario else sorted(Path('scenarios/phase4').glob('*.json'))
    evidence = {}
    for scenario in scenarios:
        summary = compare(scenario,args.output/scenario.stem,args.policies)
        evidence[scenario.stem] = summary
        print(scenario.stem, {p:{'delivered':r['delivered'],'route_changes':r['route_changes'],
                               'fallbacks':r['prediction']['fallback_count']} for p,r in summary['policies'].items()},flush=True)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        args.evidence.write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
