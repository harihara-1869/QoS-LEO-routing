"""Compile against the pinned ns-3 wheel; never imports Cppyy into the simulator."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = '3.44.post0'


def build_engine(ns3_python: str | None = None) -> Path:
    default_python = str(ROOT / '.venv-ns3/bin/python') if (ROOT / '.venv-ns3/bin/python').exists() else sys.executable
    python = ns3_python or os.environ.get('LEO_NS3_PYTHON', default_python)
    query = (
        'import importlib.metadata,json; from pathlib import Path; '
        'd=importlib.metadata.distribution("ns3"); '
        'print(json.dumps({"version":d.version,"root":str(Path(d.locate_file("ns3")).resolve())}))'
    )
    try:
        result = subprocess.run([python, '-c', query], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError('Install requirements/ns3.txt in .venv-ns3 or set LEO_NS3_PYTHON to that environment') from exc
    info = json.loads(result.stdout)
    if info['version'] != VERSION:
        raise ValueError(f'Expected ns3=={VERSION}; found {info["version"]}')
    compiler = shutil.which('g++')
    if compiler is None:
        raise RuntimeError('A C++20-capable g++ compiler is required')
    nsroot = Path(info['root'])
    lib = nsroot / 'lib64'
    source = ROOT / 'packet_backend/engine.cc'
    compiler_version = subprocess.run([compiler, '--version'], capture_output=True, text=True, check=True).stdout
    inputs = source.read_bytes() + Path(__file__).read_bytes()
    inputs += b''.join(p.read_bytes() for p in sorted(source.parent.glob('*.h')))
    key = hashlib.sha256(inputs + str(nsroot).encode() + compiler_version.encode()).hexdigest()[:16]
    directory = ROOT / 'runs/build' / key
    binary = directory / 'leo-ns3'
    if binary.exists():
        return binary
    directory.mkdir(parents=True, exist_ok=True)
    command = [compiler, '-std=c++20', '-O2', '-Wall', '-Wextra', str(source), '-o', str(binary),
               '-isystem', str(nsroot / 'include'), '-L', str(lib), f'-Wl,-rpath,{lib}', f'-Wl,-rpath-link,{lib}']
    command += [f'-l:libns3.44-{module}.so' for module in
                ('applications', 'point-to-point', 'internet', 'traffic-control', 'network', 'core')]
    result = subprocess.run(command, capture_output=True, text=True)
    (directory / 'build.log').write_text(result.stdout + result.stderr)
    (directory / 'build.json').write_text(json.dumps({'command': command, 'compiler': compiler_version, **info}, indent=2))
    if result.returncode:
        binary.unlink(missing_ok=True)
        raise RuntimeError(f'Engine compilation failed; see {directory / "build.log"}')
    return binary
