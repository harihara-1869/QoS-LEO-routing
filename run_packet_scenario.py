"""Run Phase 2 packet simulation with the compiled ns-3 backend."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time

from packet_backend.build import ROOT, build_engine
from packet_backend.controller import execute, shortest_routes
from packet_backend.results import summarize
from packet_backend.scenario import prepare


def _run(scenario, output, *, ns3_python=None, policy=shortest_routes, timeout_s=120):
    config = json.loads(Path(scenario).read_text()) if not isinstance(scenario, dict) else scenario
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = prepare(config, output)
    binary = build_engine(ns3_python)
    start = time.perf_counter()
    control = execute(binary, plan, output, policy, timeout_s)
    elapsed = time.perf_counter()-start
    result = summarize(plan,output,control)
    encoded = json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n'
    (output/'results.json').write_text(encoded)
    sources = [Path(__file__).resolve(), *sorted((ROOT/'packet_backend').glob('*.py')),
               ROOT/'packet_backend/engine.cc', ROOT/'logic_module.py', ROOT/'setup.py',ROOT/'sim_man.py',
               ROOT/'requirements.txt', ROOT/'requirements-ns3.txt']
    revision = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    dirty = bool(subprocess.run(['git','status','--porcelain'],cwd=ROOT,capture_output=True,text=True).stdout)
    manifest = {'result_sha256':hashlib.sha256(encoded.encode()).hexdigest(), 'git_revision':revision,
                'working_tree_dirty':dirty, 'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'ns3':'3.44.post0', 'policy':f'{policy.__module__}.{policy.__qualname__}',
                'dependencies':{p:importlib.metadata.version(p) for p in ('numpy','skyfield','sgp4','igraph')},
                'engine_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                'engine_wall_seconds':elapsed, 'controller_wall_seconds':control['controller_wall_seconds']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return result


def run(scenario, output, *, ns3_python=None, policy=shortest_routes, timeout_s=120):
    """Overwrite generated results in output; a failed run never retains stale success files."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ('results.json', 'manifest.json'):
        (output / name).unlink(missing_ok=True)
    status = output / 'status.json'
    status.write_text(json.dumps({'status': 'running'}) + '\n')
    try:
        result = _run(scenario, output, ns3_python=ns3_python, policy=policy, timeout_s=timeout_s)
    except Exception as exc:
        status.write_text(json.dumps({'status': 'failed', 'error': str(exc)}) + '\n')
        raise
    status.write_text(json.dumps({'status': 'complete'}) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',default='scenarios/packet_baseline.json')
    parser.add_argument('--output',default='runs/packet-baseline')
    parser.add_argument('--ns3-python',help='Python executable in the pinned ns-3 environment')
    args = parser.parse_args()
    print(json.dumps(run(args.scenario,args.output,ns3_python=args.ns3_python)['flows'],indent=2))
