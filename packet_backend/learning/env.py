"""Gym-compatible synchronous environment wrapping the authoritative ns-3 packet engine."""
from copy import deepcopy
import json
from pathlib import Path
from queue import Queue, Empty
import subprocess
from threading import Thread
import time
from typing import Any, Dict, Tuple
import numpy as np

from packet_backend.build import ensure_engine
from packet_backend.controller import validate_routes
from packet_backend.learning.encoder import GraphObservationEncoder, NeuroSymbolicTreeDecoder
from packet_backend.prediction import OrbitalForecaster
from packet_backend.qos import CLASSES
from packet_backend.scenario import prepare


class SatelliteRoutingEnv:
    """Synchronous RL training environment interacting directly with ns-3 via stdio pipes."""

    def __init__(self,
                 scenario_path: Path | str,
                 output_dir: Path | str,
                 timeout_s: float = 60.0):
        self.scenario_path = Path(scenario_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s

        self.encoder = GraphObservationEncoder()
        self.decoder = NeuroSymbolicTreeDecoder()

        self.process = None
        self.reader_thread = None
        self.inbox = Queue()
        self.plan = None
        self.binary = None
        self.orbital = None

        self.last_observation = None
        self.last_queues = None
        self.current_step = 0
        self.max_steps = 100

    def _read_line(self) -> str:
        try:
            line = self.inbox.get(timeout=self.timeout_s)
        except Empty as exc:
            raise TimeoutError("ns-3 observation timed out in RL environment") from exc
        if line is None:
            raise RuntimeError(f"ns-3 engine terminated prematurely; see {self.output_dir / 'engine.stderr'}")
        return line.strip()

    def _stdout_reader(self, stream):
        for line in stream:
            self.inbox.put(line)
        self.inbox.put(None)

    def reset(self, seed: int | None = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        self.close()
        self.current_step = 0
        self.decoder.reset()

        raw_scenario = json.loads(self.scenario_path.read_text())
        if seed is not None:
            raw_scenario['seed'] = seed

        self.binary = ensure_engine()
        self.plan = prepare(raw_scenario, self.output_dir)

        # Initialize causal orbital forecaster if ephemeris available
        if self.plan['topology_source'] == 'skyfield_sgp4':
            from constellation.omm import get_satellite_data
            source = self.plan['source_scenario']
            self.orbital = OrbitalForecaster(
                get_satellite_data(csv_file=self.output_dir / 'constellation.csv'),
                source['epoch'], source['links'], source['ground_stations'], self.plan['prediction'],
                orbital_start_s=source.get('orbital_start_s', 0), topology_step_s=source['step_s']
            )

        destinations = sorted({f['dst'] for f in self.plan['flows']} |
                              {f['src'] for f in self.plan['flows'] if f['protocol'] == 'tcp'})
        self.destinations = destinations

        # Launch ns-3 subprocess
        stderr_file = (self.output_dir / 'engine.stderr').open('w')
        self.process = subprocess.Popen(
            [str(self.binary), str(self.output_dir / 'engine.plan'), str(self.output_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file,
            text=True, bufsize=1
        )
        self.reader_thread = Thread(target=self._stdout_reader, args=(self.process.stdout,), daemon=True)
        self.reader_thread.start()

        # Read first observation
        observation = self._read_observation()
        self.last_observation = observation
        self.last_queues = { (q['link_id'], q['direction']): deepcopy(q) for q in observation['queues'] }

        orbital_forecasts = {}
        if self.orbital:
            raw_forecasts = self.orbital.predict(observation)
            orbital_forecasts = {f['link_id']: f for f in raw_forecasts}

        state_vector = self.encoder.encode(observation, orbital_forecasts)
        return state_vector, {"observation": observation}

    def _read_observation(self) -> Dict[str, Any]:
        header = self._read_line().split()
        if len(header) == 1 and header[0] == 'DONE':
            return None
        if len(header) != 3 or header[0] != 'STATE':
            raise RuntimeError(f"Unexpected observation from engine: {header}")

        time_s = float(header[1])
        num_queues = int(header[2])

        queues = []
        for _ in range(num_queues):
            row = list(map(int, self._read_line().split()))
            link, direction, packets, size = row[:4]
            q_entry = {'link_id': link, 'direction': direction, 'packets': packets, 'bytes': size}
            if self.plan['qos']:
                q_entry['classes'] = {
                    name: {'packets': row[4+2*i], 'bytes': row[5+2*i]} for i, name in enumerate(CLASSES)
                }
                for i, name in enumerate(CLASSES):
                    q_entry['classes'][name].update(zip(
                        ('arrived_bytes', 'served_bytes', 'rejected_bytes'),
                        row[10+3*i:13+3*i]
                    ))
            queues.append(q_entry)

        if self._read_line() != 'END':
            raise RuntimeError("Invalid observation terminator from ns-3")

        # Find matching topology snapshot
        snapshot = min(self.plan['snapshots'], key=lambda s: abs(s['time_s'] - time_s))
        links = [{**self.plan['links'][edge['id']], 'delay_s': edge['delay_s']} for edge in snapshot['links']]

        observation = {
            'time_s': time_s,
            'nodes': list(self.plan['nodes']),
            'links': links,
            'queues': queues,
            'destinations': self.destinations,
            'qos': self.plan['qos'],
            'mtu_bytes': self.plan['mtu_bytes'],
            'non_transit_nodes': [] if self.plan['allow_ground_transit'] else [
                i for i, n in enumerate(self.plan['nodes']) if n in {gs[0] for gs in self.plan['source_scenario'].get('ground_stations', [])}
            ],
            'active_flows': [
                {k: f[k] for k in ('id', 'src', 'dst', 'class_id', 'flow_type', 'protocol', 'size', 'deadline_s', 'min_goodput_bps')}
                for f in self.plan['flows'] if f['start'] <= time_s < f['end'] and (f['protocol'] == 'tcp' or f['rate'] > 0)
            ]
        }
        return observation

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, Dict[str, float], bool, bool, Dict[str, Any]]:
        self.current_step += 1

        # 1. Decode continuous action potentials into cycle-free routing trees
        num_edges = len(self.last_observation['links'])
        potentials = action[:num_edges * 3].reshape((num_edges, 3))

        orbital_forecasts = {}
        if self.orbital:
            raw_forecasts = self.orbital.predict(self.last_observation)
            orbital_forecasts = {f['link_id']: f for f in raw_forecasts}

        routes = self.decoder.decode(self.last_observation, potentials, orbital_forecasts)
        validate_routes(routes, self.last_observation)

        # 2. Write routes to engine stdin
        rows = [(*key, nxt) for key, nxt in sorted(routes.items())]
        self.process.stdin.write(f'ROUTES {len(rows)}\n' + ''.join(' '.join(map(str, row)) + '\n' for row in rows))
        self.process.stdin.flush()

        # 3. Read subsequent observation
        next_obs = self._read_observation()
        terminated = (next_obs is None)

        if terminated:
            self.close()
            dummy_state = np.zeros(self.encoder.total_dim, dtype=np.float32)
            return dummy_state, 0.0, {"cost_control": 0.0, "cost_realtime": 0.0}, True, False, {}

        # 4. Compute step rewards & constraint violation costs from counter differences
        delta_served_bulk = 0
        delta_rejected_bulk = 0
        delta_rejected_ctrl = 0
        delta_rejected_rt = 0

        curr_queues = { (q['link_id'], q['direction']): q for q in next_obs['queues'] }
        for key, curr_q in curr_queues.items():
            prev_q = self.last_queues.get(key)
            if not prev_q:
                continue
            curr_c = curr_q.get('classes', {})
            prev_c = prev_q.get('classes', {})

            # Bulk
            delta_served_bulk += max(0, curr_c.get('BULK', {}).get('served_bytes', 0) - prev_c.get('BULK', {}).get('served_bytes', 0))
            delta_rejected_bulk += max(0, curr_c.get('BULK', {}).get('rejected_bytes', 0) - prev_c.get('BULK', {}).get('rejected_bytes', 0))

            # Control
            delta_rejected_ctrl += max(0, curr_c.get('CONTROL', {}).get('rejected_bytes', 0) - prev_c.get('CONTROL', {}).get('rejected_bytes', 0))

            # Realtime
            delta_rejected_rt += max(0, curr_c.get('REALTIME', {}).get('rejected_bytes', 0) - prev_c.get('REALTIME', {}).get('rejected_bytes', 0))

        # Reward formulation: Maximize delivered Bulk throughput, penalize bulk loss
        reward = (delta_served_bulk / 1e5) - (2.0 * delta_rejected_bulk / 1e5)

        # Constraint costs: Penalty for Control/Realtime packet rejections
        cost_ctrl = float(delta_rejected_ctrl > 0)
        cost_rt = float(delta_rejected_rt > 0)
        costs = {"cost_control": cost_ctrl, "cost_realtime": cost_rt}

        self.last_observation = next_obs
        self.last_queues = curr_queues

        next_state = self.encoder.encode(next_obs, orbital_forecasts)
        return next_state, reward, costs, False, False, {"observation": next_obs}

    def close(self):
        if self.process:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.process = None
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1)
        while not self.inbox.empty():
            try:
                self.inbox.get_nowait()
            except Empty:
                break

