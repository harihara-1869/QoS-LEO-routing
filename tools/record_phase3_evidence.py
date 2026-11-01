"""Record the five matched Phase 3 comparisons and their source/result hashes."""
import argparse
import json
from pathlib import Path
from experiments.compare_baselines import compare
from packet_backend.workloads import CASES


def record(output, evidence, seed):
    rows = []
    for case in CASES:
        summary = compare(case, output/case, seed)
        for policy in summary['policies']:
            directory = output/case/policy
            result = json.loads((directory/'results.json').read_text())
            manifest = json.loads((directory/'manifest.json').read_text())
            rows.append({'case':case,'policy':policy,'scenario_sha256':summary['scenario_sha256'],
                         'result_sha256':manifest['result_sha256'], 'classes':result['qos']['classes'],
                         'bulk_jain_active_goodput':result['qos']['bulk_jain_active_goodput'],
                         'bulk_service':result['qos']['bulk_service'],
                         'route_changes':sum(f['route_changes'] for f in result['flows'])})
    payload = {'schema_version':1, 'seed':seed, 'ns3':manifest['ns3'],
               'dependencies':manifest['dependencies'],'source_sha256':manifest['source_sha256'],
               'note':'Controlled synthetic smoke cases, not calibrated research results; all policies share scheduler/traffic/topology.',
               'runs':rows}
    evidence.parent.mkdir(parents=True,exist_ok=True)
    evidence.write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')
    print(f'Recorded {len(rows)} runs in {evidence}')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('runs/phase3'))
    parser.add_argument('--evidence',type=Path,default=Path('runs/phase3/evidence.json'))
    parser.add_argument('--seed',type=int,default=7)
    args=parser.parse_args()
    record(args.output,args.evidence,args.seed)
