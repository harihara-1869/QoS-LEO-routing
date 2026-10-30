"""Generate replayable Phase 2 example outputs and a compact evidence summary.

Run from the repository root: .venv/bin/python -m tools.record_phase2_evidence
The independent acceptance checks live in tests/test_packet_backend.py.
"""
import argparse
import json
from pathlib import Path
import subprocess

from packet_backend.build import ROOT, build_engine
from run_packet_scenario import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='runs/phase2-evidence')
    args=parser.parse_args()
    output=Path(args.output)
    summary={'schema_version':1,'ns3_version':'3.44.post0','cases':{}}
    check=subprocess.run([str(build_engine()),'--check-reno'],capture_output=True,text=True,check=True)
    summary['reno_arithmetic']={'slow_start_cwnd_bytes':int(check.stdout.split()[0]),
                                'loss_ssthresh_bytes':int(check.stdout.split()[1]),
                                'avoidance_cwnd_bytes':int(check.stdout.split()[2])}
    for scenario in sorted((ROOT/'scenarios/phase2').glob('*.json')):
        run_dir=output/scenario.stem
        result=run(scenario,run_dir)
        manifest=json.loads((run_dir/'manifest.json').read_text())
        summary['cases'][scenario.stem]={
            'scenario':str(scenario.relative_to(ROOT)), 'flows':result['flows'],
            'first_udp_packet':result['udp_packets'][0] if result['udp_packets'] else None,
            'link_transitions':sum(e['kind']=='link' and e['time_s']>0 for e in result['events']),
            'max_queue_packets':max((q['max_packets'] for q in result['queues']),default=0),
            'cwnd_reductions':sum(e['kind']=='cwnd' and e['value']<e['a'] for e in result['events']),
            'result_sha256':manifest['result_sha256'], 'source_sha256':manifest['source_sha256'],
            'engine_wall_seconds':manifest['engine_wall_seconds'],
            'controller_wall_seconds':manifest['controller_wall_seconds']}
        print(scenario.stem,result['flows'],flush=True)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':
    main()
