"""
Standalone Kaggle-compatible training for Neuro-Symbolic Constrained RL (NS-CRPO).

The original training relied on a compiled C++ ns-3 binary for the packet
simulation loop, which is unavailable on Kaggle.  This script replaces that
with a pure-Python satellite routing environment that:

  1. Uses the real Skyfield orbital model to generate dynamic topology snapshots
  2. Simulates DRR-scheduled packet queuing in Python (no compiled engine)
  3. Computes realistic rewards (bulk throughput) and constraint costs
     (control/realtime deadline violations)
  4. Trains the same NeuroSymbolicActorCritic model with PPO-Lagrangian

Usage (Kaggle notebook cell):
    !python -m experiments.train_kaggle --episodes 80 --output-dir /kaggle/working/runs/nscrpo

After training, the script produces:
  - best_model.pt / final_model.pt  (frozen checkpoints + manifests)
  - train_history.json              (per-episode metrics)
  - Inline matplotlib training curves (reward, violations, losses, multipliers)
"""

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Optional: nicer progress on Kaggle
# ---------------------------------------------------------------------------
try:
    from tqdm.auto import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# ---------------------------------------------------------------------------
# Torch
# ---------------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Normal
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    print("ERROR: PyTorch is required. pip install torch", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Matplotlib (for final plots; non-fatal if missing)
# ---------------------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")          # headless for Kaggle
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ============================================================================
# 1.  PURE-PYTHON SATELLITE ROUTING ENVIRONMENT
# ============================================================================

class PythonSatRoutingEnv:
    """
    Lightweight pure-Python LEO routing environment for RL training.

    Instead of launching an ns-3 subprocess, this environment:
      - Builds a real Walker-constellation topology using Skyfield/SGP4.
      - Simulates DRR-like packet queuing across the ISL/ground links.
      - Steps at a configurable control interval, computing served/rejected
        bytes for each QoS class and computing rewards/costs identical to
        the original ns-3 env formulation.
    """

    # QoS class names matching the project convention
    CLASSES = ("CONTROL", "REALTIME", "BULK")

    def __init__(
        self,
        scenario_path: Path | str,
        output_dir: Path | str,
        max_steps: int = 50,
        control_interval_s: float = 0.05,
    ):
        self.scenario_path = Path(scenario_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_steps = max_steps
        self.control_dt = control_interval_s

        # Will be populated on reset()
        self.plan = None
        self.time_s = 0.0
        self.step_idx = 0

        # Per-link, per-direction, per-class queue state
        self.queues: Dict = {}
        # Cumulative counters
        self.counters: Dict = {}

        # Encoder / decoder (reuse existing project code)
        from packet_backend.learning.encoder import (
            GraphObservationEncoder,
            NeuroSymbolicTreeDecoder,
        )
        self.encoder = GraphObservationEncoder()
        self.decoder = NeuroSymbolicTreeDecoder()

        # Orbital forecaster (optional)
        self.orbital = None

        # Cache last observation
        self._last_obs: Optional[dict] = None
        self._last_queues_snapshot: Optional[dict] = None

    # ------------------------------------------------------------------
    # Topology helpers
    # ------------------------------------------------------------------

    def _build_topology(self, scenario: dict):
        """Generate orbital snapshots using constellation module."""
        from constellation.omm import generate_omm_csv, get_satellite_data
        from constellation.snapshots import TopologySnapshots
        from constellation.topology import LogicalConfig

        csv_path = str(self.output_dir / "constellation.csv")
        generate_omm_csv(csv_path, **scenario["constellation"], epoch=scenario["epoch"])
        satellites = get_satellite_data(csv_file=csv_path)

        link_cfg = LogicalConfig(**scenario["links"])
        gs_list = scenario["ground_stations"]
        orbital_start = scenario.get("orbital_start_s", 0)
        step_s = scenario["step_s"]
        duration = scenario["duration_s"]

        snaps = TopologySnapshots(satellites, scenario["epoch"], link_cfg, gs_list, orbital_start)
        for tick in range(math.ceil(duration / step_s)):
            snaps.update_topology(tick * step_s)

        return snaps, satellites

    # ------------------------------------------------------------------
    # Flow / traffic model
    # ------------------------------------------------------------------

    def _init_flow_state(self, scenario: dict, node_ids: dict):
        """Parse flows from scenario and build internal flow records."""
        from packet_backend.qos import classify, normalize

        qos_cfg = normalize(scenario.get("qos"))
        flows = []
        for f in scenario["flows"]:
            svc = classify(f, qos_cfg)
            flows.append({
                **svc,
                "id": f["flow_id"],
                "src": node_ids[f["src"]],
                "dst": node_ids[f["dst"]],
                "protocol": f.get("protocol", "udp").lower(),
                "start": f["start_time"],
                "end": f["end_time"],
                "rate": f.get("data_rate_bps", 0),
                "size": f.get("packet_size_bytes", 1000),
            })
        return flows, qos_cfg

    # ------------------------------------------------------------------
    # Queue simulation
    # ------------------------------------------------------------------

    def _init_queues(self, links: list):
        """Initialize empty per-link, per-direction, per-class queues."""
        self.queues = {}
        self.counters = {}
        for link in links:
            lid = link["id"]
            for d in (0, 1):
                key = (lid, d)
                self.queues[key] = {cls: 0 for cls in self.CLASSES}
                self.counters[key] = {
                    cls: {"arrived_bytes": 0, "served_bytes": 0, "rejected_bytes": 0}
                    for cls in self.CLASSES
                }

    def _simulate_traffic_step(self, routes: dict, dt: float):
        """
        Simplified DRR-like packet simulation for one control interval.

        For each active flow:
          - Compute bytes generated in dt
          - Route them hop-by-hop using the provided routing table
          - At each hop, enqueue bytes into the appropriate class queue
          - Service queues proportionally (DRR weights)
          - If a queue overflows, count rejected bytes
        """
        qos_weights = {"CONTROL": 4, "REALTIME": 2, "BULK": 1}
        if self.plan_qos:
            qos_weights = self.plan_qos.get("weights", qos_weights)
        total_w = sum(qos_weights.values())
        max_queue_bytes = 40 * 9000  # queue_packets * mtu_bytes

        # --- Arrivals ---
        for flow in self._active_flows:
            cls_name = flow["flow_type"]
            bytes_generated = int(flow["rate"] * dt / 8)
            if bytes_generated <= 0:
                continue

            src, dst = flow["src"], flow["dst"]
            class_id = self.CLASSES.index(cls_name)

            # Walk the routing path from src to dst
            current = src
            hops = 0
            while current != dst and hops < 30:
                key = (class_id, current, dst)
                nxt = routes.get(key)
                if nxt is None:
                    # No route — count as rejected at source
                    # Find any link from current
                    for lk in self._links:
                        if lk["a"] == current or lk["b"] == current:
                            direction = 0 if lk["a"] == current else 1
                            qk = (lk["id"], direction)
                            if qk in self.counters:
                                self.counters[qk][cls_name]["arrived_bytes"] += bytes_generated
                                self.counters[qk][cls_name]["rejected_bytes"] += bytes_generated
                            break
                    break

                # Find the link between current and nxt
                link_id, direction = self._find_link(current, nxt)
                if link_id is None:
                    break

                qk = (link_id, direction)
                self.counters[qk][cls_name]["arrived_bytes"] += bytes_generated
                current_q = self.queues[qk][cls_name]

                if current_q + bytes_generated > max_queue_bytes:
                    # Partial accept
                    accept = max(0, max_queue_bytes - current_q)
                    self.queues[qk][cls_name] = max_queue_bytes
                    self.counters[qk][cls_name]["rejected_bytes"] += (bytes_generated - accept)
                    self.counters[qk][cls_name]["arrived_bytes"] += 0  # already counted
                    bytes_generated = accept  # reduced for next hop
                else:
                    self.queues[qk][cls_name] += bytes_generated

                current = nxt
                hops += 1

        # --- Service (DRR-proportional draining) ---
        for link in self._links:
            cap_bps = link["capacity_bps"]
            service_bytes = int(cap_bps * dt / 8)

            for d in (0, 1):
                qk = (link["id"], d)
                remaining = service_bytes
                # Serve in priority order: CONTROL > REALTIME > BULK
                for cls_name in self.CLASSES:
                    w = qos_weights[cls_name] / total_w
                    cls_budget = int(service_bytes * w) + 1  # +1 to avoid starving
                    can_serve = min(self.queues[qk][cls_name], cls_budget, remaining)
                    self.queues[qk][cls_name] -= can_serve
                    self.counters[qk][cls_name]["served_bytes"] += can_serve
                    remaining -= can_serve

    def _find_link(self, node_a: int, node_b: int) -> Tuple[Optional[int], int]:
        """Find link id and direction for a hop from node_a to node_b."""
        for link in self._links:
            if link["a"] == node_a and link["b"] == node_b:
                return link["id"], 0
            if link["b"] == node_a and link["a"] == node_b:
                return link["id"], 1
        return None, 0

    # ------------------------------------------------------------------
    # Observation builder
    # ------------------------------------------------------------------

    def _build_observation(self) -> dict:
        """Build an observation dict matching the ns-3 controller format."""
        queues_list = []
        for link in self._links:
            for d in (0, 1):
                qk = (link["id"], d)
                q_entry = {
                    "link_id": link["id"],
                    "direction": d,
                    "packets": sum(self.queues[qk][c] // 1000 for c in self.CLASSES),
                    "bytes": sum(self.queues[qk][c] for c in self.CLASSES),
                    "classes": {},
                }
                for cls_name in self.CLASSES:
                    q_entry["classes"][cls_name] = {
                        "packets": self.queues[qk][cls_name] // 1000,
                        "bytes": self.queues[qk][cls_name],
                        "arrived_bytes": self.counters[qk][cls_name]["arrived_bytes"],
                        "served_bytes": self.counters[qk][cls_name]["served_bytes"],
                        "rejected_bytes": self.counters[qk][cls_name]["rejected_bytes"],
                    }
                queues_list.append(q_entry)

        self._active_flows = [
            f for f in self._flows
            if f["start"] <= self.time_s < f["end"] and f["rate"] > 0
        ]

        observation = {
            "time_s": self.time_s,
            "nodes": list(self._node_names),
            "links": self._links,
            "queues": queues_list,
            "destinations": self._destinations,
            "qos": self.plan_qos,
            "mtu_bytes": 9000,
            "non_transit_nodes": self._non_transit,
            "active_flows": [
                {
                    "id": f["id"], "src": f["src"], "dst": f["dst"],
                    "class_id": f["class_id"], "flow_type": f["flow_type"],
                    "protocol": f["protocol"], "size": f["size"],
                    "deadline_s": f.get("deadline_s"), "min_goodput_bps": f.get("min_goodput_bps"),
                }
                for f in self._active_flows
            ],
        }
        return observation

    # ------------------------------------------------------------------
    # Gym-like interface
    # ------------------------------------------------------------------

    def reset(self, seed: int | None = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset the environment, rebuild topology, return initial state."""
        if seed is not None:
            np.random.seed(seed)

        self.decoder.reset()
        self.time_s = 0.0
        self.step_idx = 0

        raw = json.loads(self.scenario_path.read_text())
        if seed is not None:
            raw["seed"] = seed

        # Build topology
        snaps_obj, satellites = self._build_topology(raw)
        snapshots = snaps_obj.snapshots
        self._node_names = snapshots[0]["nodes"]
        node_ids = {name: i for i, name in enumerate(self._node_names)}

        # Build link catalogue from first snapshot
        C_KM_S = 299792.458
        link_pairs = {}
        link_cfg = raw["links"]
        isl_cap = link_cfg.get("isl_capacity_bps", 10_000_000)
        gs_cap = link_cfg.get("ground_capacity_bps", 2_000_000)
        queue_pkts = raw.get("network", {}).get("queue_packets", 40)

        gs_names = {gs[0] for gs in raw["ground_stations"]}

        for snap in snapshots:
            for edge in snap["links"]:
                a_name, b_name = edge["a"], edge["b"]
                pair = tuple(sorted((node_ids[a_name], node_ids[b_name])))
                is_ground = a_name in gs_names or b_name in gs_names
                cap = gs_cap if is_ground else isl_cap
                if pair not in link_pairs:
                    link_pairs[pair] = {
                        "id": len(link_pairs),
                        "a": pair[0], "b": pair[1],
                        "capacity_bps": cap,
                        "queue_packets": queue_pkts,
                        "delay_s": edge["distance_km"] / C_KM_S,
                    }

        self._links = list(link_pairs.values())
        self._snapshots = snapshots

        # Non-transit ground nodes
        self._non_transit = []
        if not raw.get("allow_ground_transit", True):
            self._non_transit = [
                node_ids[gs[0]] for gs in raw["ground_stations"]
                if gs[0] in node_ids
            ]

        # Flows
        self._flows, self.plan_qos = self._init_flow_state(raw, node_ids)
        self._destinations = sorted(
            {f["dst"] for f in self._flows} |
            {f["src"] for f in self._flows if f["protocol"] == "tcp"}
        )

        # Init queues
        self._init_queues(self._links)

        # Build orbital forecaster
        self.orbital = None
        try:
            from packet_backend.prediction import OrbitalForecaster
            from packet_backend.prediction import settings as pred_settings
            pred_cfg = pred_settings(raw.get("prediction"))
            self.orbital = OrbitalForecaster(
                satellites, raw["epoch"], raw["links"],
                raw["ground_stations"], pred_cfg,
                orbital_start_s=raw.get("orbital_start_s", 0),
                topology_step_s=raw["step_s"],
            )
        except Exception:
            pass  # Proceed without orbital forecasts

        # Build first observation
        obs = self._build_observation()
        self._last_obs = obs
        self._last_queues_snapshot = self._snapshot_counters()

        orbital_forecasts = self._get_orbital_forecasts(obs)
        state = self.encoder.encode(obs, orbital_forecasts)
        return state, {"observation": obs}

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, Dict, bool, bool, Dict]:
        """Take an action (edge potentials), simulate one control step, return next state."""
        self.step_idx += 1

        # 1. Decode action into routes
        num_edges = len(self._links)
        potentials = action[:num_edges * 3].reshape((num_edges, 3))

        orbital_forecasts = self._get_orbital_forecasts(self._last_obs)
        routes = self.decoder.decode(self._last_obs, potentials, orbital_forecasts)

        # 2. Simulate traffic for one control interval
        self._simulate_traffic_step(routes, self.control_dt)
        self.time_s += self.control_dt

        # 3. Update link delays from closest topology snapshot
        self._update_link_delays()

        # 4. Build next observation
        next_obs = self._build_observation()

        # 5. Compute reward and costs from counter differences
        prev_snap = self._last_queues_snapshot
        curr_snap = self._snapshot_counters()

        delta_served_bulk = 0
        delta_rejected_bulk = 0
        delta_rejected_ctrl = 0
        delta_rejected_rt = 0

        for key in curr_snap:
            prev = prev_snap.get(key, {})
            curr = curr_snap[key]
            delta_served_bulk += max(0, curr.get("BULK_served", 0) - prev.get("BULK_served", 0))
            delta_rejected_bulk += max(0, curr.get("BULK_rejected", 0) - prev.get("BULK_rejected", 0))
            delta_rejected_ctrl += max(0, curr.get("CONTROL_rejected", 0) - prev.get("CONTROL_rejected", 0))
            delta_rejected_rt += max(0, curr.get("REALTIME_rejected", 0) - prev.get("REALTIME_rejected", 0))

        # Reward: maximize delivered bulk throughput, penalize loss
        reward = (delta_served_bulk / 1e5) - (2.0 * delta_rejected_bulk / 1e5)

        # Constraint costs
        cost_ctrl = float(delta_rejected_ctrl > 0)
        cost_rt = float(delta_rejected_rt > 0)
        costs = {"cost_control": cost_ctrl, "cost_realtime": cost_rt}

        # Check termination
        terminated = self.time_s >= self._duration_s or self.step_idx >= self.max_steps
        truncated = False

        self._last_obs = next_obs
        self._last_queues_snapshot = curr_snap

        orbital_forecasts = self._get_orbital_forecasts(next_obs)
        next_state = self.encoder.encode(next_obs, orbital_forecasts)

        info = {
            "observation": next_obs,
            "delta_served_bulk": delta_served_bulk,
            "delta_rejected_bulk": delta_rejected_bulk,
            "delta_rejected_ctrl": delta_rejected_ctrl,
            "delta_rejected_rt": delta_rejected_rt,
        }
        return next_state, reward, costs, terminated, truncated, info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_orbital_forecasts(self, obs: dict) -> dict:
        if self.orbital:
            try:
                raw = self.orbital.predict(obs)
                return {f["link_id"]: f for f in raw}
            except Exception:
                pass
        return {}

    def _snapshot_counters(self) -> dict:
        snap = {}
        for key, cls_counters in self.counters.items():
            snap[key] = {}
            for cls_name, vals in cls_counters.items():
                snap[key][f"{cls_name}_served"] = vals["served_bytes"]
                snap[key][f"{cls_name}_rejected"] = vals["rejected_bytes"]
        return snap

    def _update_link_delays(self):
        """Update link delays from the closest topology snapshot."""
        if not self._snapshots:
            return
        C_KM_S = 299792.458
        node_ids = {name: i for i, name in enumerate(self._node_names)}
        closest = min(self._snapshots, key=lambda s: abs(s["time_s"] - self.time_s))
        link_by_pair = {(l["a"], l["b"]): l for l in self._links}
        for edge in closest["links"]:
            a_id, b_id = node_ids[edge["a"]], node_ids[edge["b"]]
            pair = tuple(sorted((a_id, b_id)))
            link = link_by_pair.get(pair)
            if link:
                link["delay_s"] = edge["distance_km"] / C_KM_S

    @property
    def _duration_s(self):
        raw = json.loads(self.scenario_path.read_text())
        return raw["duration_s"]

    def close(self):
        pass


# ============================================================================
# 2.  ROLLOUT BUFFER
# ============================================================================

class RolloutBuffer:
    """Stores experience tuples for PPO batch updates."""

    __slots__ = (
        "states", "actions", "log_probs", "rewards",
        "costs_ctrl", "costs_rt", "dones",
        "values_primal", "values_ctrl", "values_rt",
    )

    def __init__(self):
        self.states: List[np.ndarray] = []
        self.actions: List[np.ndarray] = []
        self.log_probs: List[float] = []
        self.rewards: List[float] = []
        self.costs_ctrl: List[float] = []
        self.costs_rt: List[float] = []
        self.dones: List[bool] = []
        self.values_primal: List[float] = []
        self.values_ctrl: List[float] = []
        self.values_rt: List[float] = []

    def clear(self):
        for attr in self.__slots__:
            getattr(self, attr).clear()

    def __len__(self):
        return len(self.rewards)


# ============================================================================
# 3.  ACTOR-CRITIC MODEL  (reuse project's NeuroSymbolicActorCritic)
# ============================================================================
# We import the project's own model but provide a local fallback for isolation.

try:
    from packet_backend.learning.models import NeuroSymbolicActorCritic
except ImportError:
    # Inline fallback — identical architecture
    class NeuroSymbolicActorCritic(nn.Module):
        def __init__(self, state_dim, num_edges=388, num_classes=3, hidden_dim=256):
            super().__init__()
            self.num_edges = num_edges
            self.num_classes = num_classes
            self.action_dim = num_edges * num_classes

            self.backbone = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.LeakyReLU(0.1),
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.LayerNorm(hidden_dim // 2),
                nn.LeakyReLU(0.1),
            )
            self.actor_mean = nn.Sequential(
                nn.Linear(hidden_dim // 2, self.action_dim),
                nn.Sigmoid(),
            )
            self.actor_log_std = nn.Parameter(torch.full((self.action_dim,), -1.0))
            self.critic_primal = nn.Linear(hidden_dim // 2, 1)
            self.critic_cost_control = nn.Linear(hidden_dim // 2, 1)
            self.critic_cost_realtime = nn.Linear(hidden_dim // 2, 1)

        def get_action(self, state, deterministic=False):
            with torch.no_grad():
                features = self.backbone(state)
                mean = self.actor_mean(features)
                if deterministic:
                    action = mean
                    log_prob = torch.zeros(state.shape[0], device=state.device)
                else:
                    std = torch.exp(torch.clamp(self.actor_log_std, -2.0, 0.5))
                    dist = Normal(mean, std)
                    raw_action = dist.sample()
                    action = torch.clamp(raw_action, 0.0, 1.0)
                    log_prob = dist.log_prob(action).sum(dim=-1)
                v_primal = self.critic_primal(features)
                c_control = self.critic_cost_control(features)
                c_realtime = self.critic_cost_realtime(features)
            return action, log_prob, v_primal, c_control, c_realtime

        def evaluate(self, states, actions):
            features = self.backbone(states)
            mean = self.actor_mean(features)
            std = torch.exp(torch.clamp(self.actor_log_std, -2.0, 0.5))
            dist = Normal(mean, std)
            log_probs = dist.log_prob(actions).sum(dim=-1)
            entropy = dist.entropy().sum(dim=-1)
            feat_detach = features.detach()
            v_primal = self.critic_primal(feat_detach).squeeze(-1)
            c_control = self.critic_cost_control(feat_detach).squeeze(-1)
            c_realtime = self.critic_cost_realtime(feat_detach).squeeze(-1)
            return log_probs, entropy, v_primal, c_control, c_realtime


# ============================================================================
# 4.  PPO-LAGRANGIAN TRAINER  (standalone, no ns-3 dependency)
# ============================================================================

class PPOLagrangianTrainer:
    """PPO-Clip with primal-dual Lagrangian constraint handling."""

    def __init__(
        self,
        model: nn.Module,
        actor_lr: float = 3e-4,
        critic_lr: float = 1e-3,
        dual_lr: float = 0.05,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_eps: float = 0.2,
        target_ctrl_violation: float = 0.02,
        target_rt_violation: float = 0.05,
        entropy_coef: float = 0.01,
        device: str = "cpu",
    ):
        self.model = model.to(device)
        self.device = device
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_eps = clip_eps
        self.entropy_coef = entropy_coef

        self.eps_ctrl = target_ctrl_violation
        self.eps_rt = target_rt_violation

        self.mu_ctrl = 0.0
        self.mu_rt = 0.0
        self.dual_lr = dual_lr

        self.actor_optimizer = optim.Adam(
            list(model.backbone.parameters()) +
            list(model.actor_mean.parameters()) +
            [model.actor_log_std],
            lr=actor_lr,
        )
        self.critic_optimizer = optim.Adam(
            list(model.critic_primal.parameters()) +
            list(model.critic_cost_control.parameters()) +
            list(model.critic_cost_realtime.parameters()),
            lr=critic_lr,
        )

        self.buffer = RolloutBuffer()

    def compute_gae(
        self, rewards: list, values: list, dones: list
    ) -> Tuple[list, list]:
        advantages, returns = [], []
        gae = 0.0
        next_val = 0.0
        for t in reversed(range(len(rewards))):
            mask = 1.0 - float(dones[t])
            delta = rewards[t] + self.gamma * next_val * mask - values[t]
            gae = delta + self.gamma * self.gae_lambda * mask * gae
            advantages.insert(0, gae)
            returns.insert(0, gae + values[t])
            next_val = values[t]
        return advantages, returns

    def train_step(self, ppo_epochs: int = 4, batch_size: int = 64) -> Dict[str, float]:
        if len(self.buffer) == 0:
            return {"mu_control": self.mu_ctrl, "mu_realtime": self.mu_rt}

        # GAE computation
        adv_p, ret_p = self.compute_gae(self.buffer.rewards, self.buffer.values_primal, self.buffer.dones)
        adv_c, ret_c = self.compute_gae(self.buffer.costs_ctrl, self.buffer.values_ctrl, self.buffer.dones)
        adv_r, ret_r = self.compute_gae(self.buffer.costs_rt, self.buffer.values_rt, self.buffer.dones)

        states = torch.tensor(np.array(self.buffer.states), dtype=torch.float32, device=self.device)
        actions = torch.tensor(np.array(self.buffer.actions), dtype=torch.float32, device=self.device)
        old_lp = torch.tensor(np.array(self.buffer.log_probs), dtype=torch.float32, device=self.device)

        adv_p = torch.tensor(adv_p, dtype=torch.float32, device=self.device)
        adv_c = torch.tensor(adv_c, dtype=torch.float32, device=self.device)
        adv_r = torch.tensor(adv_r, dtype=torch.float32, device=self.device)
        ret_p = torch.tensor(ret_p, dtype=torch.float32, device=self.device)
        ret_c = torch.tensor(ret_c, dtype=torch.float32, device=self.device)
        ret_r = torch.tensor(ret_r, dtype=torch.float32, device=self.device)

        # Normalize primal advantage
        if adv_p.std() > 1e-8:
            adv_p = (adv_p - adv_p.mean()) / (adv_p.std() + 1e-8)

        # Lagrangian effective advantage
        eff_adv = adv_p - self.mu_ctrl * adv_c - self.mu_rt * adv_r

        n = states.shape[0]
        indices = np.arange(n)
        all_policy_losses, all_critic_losses = [], []

        for _ in range(ppo_epochs):
            np.random.shuffle(indices)
            for start in range(0, n, batch_size):
                idx = indices[start : start + batch_size]
                b_s = states[idx]
                b_a = actions[idx]
                b_olp = old_lp[idx]
                b_adv = eff_adv[idx]

                log_probs, entropy, v_p, c_c, c_r = self.model.evaluate(b_s, b_a)

                ratio = torch.exp(log_probs - b_olp)
                s1 = ratio * b_adv
                s2 = torch.clamp(ratio, 1.0 - self.clip_eps, 1.0 + self.clip_eps) * b_adv
                actor_loss = -torch.min(s1, s2).mean() - self.entropy_coef * entropy.mean()

                self.actor_optimizer.zero_grad()
                actor_loss.backward(retain_graph=True)
                nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
                self.actor_optimizer.step()
                all_policy_losses.append(actor_loss.item())

                c_loss = (
                    nn.MSELoss()(v_p, ret_p[idx]) +
                    nn.MSELoss()(c_c, ret_c[idx]) +
                    nn.MSELoss()(c_r, ret_r[idx])
                )
                self.critic_optimizer.zero_grad()
                c_loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
                self.critic_optimizer.step()
                all_critic_losses.append(c_loss.item())

        # Dual multiplier update
        mean_cc = float(np.mean(self.buffer.costs_ctrl))
        mean_cr = float(np.mean(self.buffer.costs_rt))
        self.mu_ctrl = max(0.0, self.mu_ctrl + self.dual_lr * (mean_cc - self.eps_ctrl))
        self.mu_rt = max(0.0, self.mu_rt + self.dual_lr * (mean_cr - self.eps_rt))

        stats = {
            "loss_policy": float(np.mean(all_policy_losses)),
            "loss_critic": float(np.mean(all_critic_losses)),
            "mu_control": float(self.mu_ctrl),
            "mu_realtime": float(self.mu_rt),
            "mean_bulk_reward": float(np.mean(self.buffer.rewards)),
            "mean_ctrl_cost": float(mean_cc),
            "mean_rt_cost": float(mean_cr),
        }
        self.buffer.clear()
        return stats

    def save_checkpoint(self, path: Path | str, scenario_tag: str = "phase5") -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), path)

        try:
            from packet_backend.learning.registry import CheckpointRegistry
            CheckpointRegistry.create_manifest(
                checkpoint_path=path,
                architecture="NeuroSymbolicActorCritic",
                state_dim=self.model.backbone[0].in_features,
                num_edges=self.model.num_edges,
                scenario_compatibility=[scenario_tag, "walker_200_satellites"],
                hyperparameters={
                    "gamma": self.gamma,
                    "clip_eps": self.clip_eps,
                    "target_ctrl_violation": self.eps_ctrl,
                    "target_rt_violation": self.eps_rt,
                },
                weights_mode="frozen",
            )
        except Exception:
            pass  # Non-fatal if registry unavailable
        return path


# ============================================================================
# 5.  PLOTTING
# ============================================================================

def plot_training_curves(history: list, output_dir: Path):
    """Generate comprehensive training metric plots."""
    if not HAS_MPL:
        print("[Warning] matplotlib not available — skipping plots")
        return

    eps = [h["episode"] for h in history]
    rewards = [h["reward"] for h in history]
    ctrl_v = [h["ctrl_violations"] for h in history]
    rt_v = [h["rt_violations"] for h in history]
    mu_c = [h["mu_ctrl"] for h in history]
    mu_r = [h["mu_rt"] for h in history]
    p_loss = [h.get("loss_policy") for h in history]
    c_loss = [h.get("loss_critic") for h in history]
    steps_per_ep = [h.get("steps", 0) for h in history]
    served = [h.get("total_served_bulk", 0) for h in history]
    rejected = [h.get("total_rejected_bulk", 0) for h in history]

    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle("NS-CRPO Training Progress — LEO Satellite QoS Routing", fontsize=15, fontweight="bold")

    # 1. Episode Reward
    ax = axes[0, 0]
    ax.plot(eps, rewards, "b-", linewidth=1.2, alpha=0.7, label="Episode Reward")
    window = min(10, max(1, len(rewards) // 5))
    if len(rewards) >= window:
        smoothed = np.convolve(rewards, np.ones(window) / window, mode="valid")
        ax.plot(eps[window - 1:], smoothed, "r-", linewidth=2.0, label=f"MA-{window}")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Bulk Reward")
    ax.set_title("Bulk Throughput Reward")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 2. Constraint Violations
    ax = axes[0, 1]
    ax.plot(eps, ctrl_v, "r-", linewidth=1.2, alpha=0.7, label="Control Violations")
    ax.plot(eps, rt_v, "orange", linewidth=1.2, alpha=0.7, label="Realtime Violations")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Violation Count")
    ax.set_title("QoS Constraint Violations")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 3. Lagrange Multipliers
    ax = axes[1, 0]
    ax.plot(eps, mu_c, "r-", linewidth=1.5, label="μ_ctrl")
    ax.plot(eps, mu_r, "purple", linewidth=1.5, label="μ_rt")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Multiplier Value")
    ax.set_title("Lagrange Multipliers (Dual Variables)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 4. Policy & Critic Losses
    ax = axes[1, 1]
    valid_pl = [(e, l) for e, l in zip(eps, p_loss) if l is not None]
    valid_cl = [(e, l) for e, l in zip(eps, c_loss) if l is not None]
    if valid_pl:
        ax.plot([x[0] for x in valid_pl], [x[1] for x in valid_pl], "g-", linewidth=1.2, label="Policy Loss")
    if valid_cl:
        ax.plot([x[0] for x in valid_cl], [x[1] for x in valid_cl], "m-", linewidth=1.2, label="Critic Loss")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Loss")
    ax.set_title("PPO Losses")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 5. Steps per Episode
    ax = axes[2, 0]
    ax.bar(eps, steps_per_ep, color="steelblue", alpha=0.7)
    ax.set_xlabel("Episode")
    ax.set_ylabel("Steps")
    ax.set_title("Steps per Episode")
    ax.grid(True, alpha=0.3, axis="y")

    # 6. Throughput Breakdown
    ax = axes[2, 1]
    ax.plot(eps, served, "g-", linewidth=1.5, label="Served Bulk (bytes)")
    ax.plot(eps, rejected, "r-", linewidth=1.5, label="Rejected Bulk (bytes)")
    ax.set_xlabel("Episode")
    ax.set_ylabel("Bytes")
    ax.set_title("Bulk Traffic: Served vs Rejected")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = output_dir / "training_curves.png"
    fig.savefig(fig_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Training] Saved training curves to {fig_path}")

    # Also show inline on Kaggle
    try:
        from IPython.display import Image, display
        display(Image(filename=str(fig_path)))
    except Exception:
        pass


def print_summary_table(history: list):
    """Print a final summary table of training results."""
    if not history:
        return

    rewards = [h["reward"] for h in history]
    ctrl_v = [h["ctrl_violations"] for h in history]
    rt_v = [h["rt_violations"] for h in history]

    # Split into quarters for trend analysis
    n = len(history)
    q_size = max(1, n // 4)
    quarters = [history[i * q_size: (i + 1) * q_size] for i in range(4)]
    quarters[-1] = history[3 * q_size:]  # Include remainder in last quarter

    print("\n" + "=" * 85)
    print("                    NS-CRPO TRAINING SUMMARY")
    print("=" * 85)
    print(f"{'Metric':<30} | {'Q1':>10} | {'Q2':>10} | {'Q3':>10} | {'Q4':>10}")
    print("-" * 85)

    for metric_name, key in [
        ("Avg Reward", "reward"),
        ("Avg Ctrl Violations", "ctrl_violations"),
        ("Avg RT Violations", "rt_violations"),
        ("Avg Steps/Episode", "steps"),
    ]:
        vals = []
        for q in quarters:
            if q:
                vals.append(np.mean([h.get(key, 0) for h in q]))
            else:
                vals.append(0)
        print(f"{metric_name:<30} | {vals[0]:>10.3f} | {vals[1]:>10.3f} | {vals[2]:>10.3f} | {vals[3]:>10.3f}")

    print("-" * 85)
    print(f"{'Final Reward':<30} | {rewards[-1]:>10.3f}")
    print(f"{'Best Reward':<30} | {max(rewards):>10.3f}")
    print(f"{'Total Training Episodes':<30} | {n:>10d}")
    print(f"{'Final μ_ctrl':<30} | {history[-1]['mu_ctrl']:>10.4f}")
    print(f"{'Final μ_rt':<30} | {history[-1]['mu_rt']:>10.4f}")
    print("=" * 85)


# ============================================================================
# 6.  MAIN TRAINING LOOP
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Kaggle-compatible NS-CRPO training for LEO QoS routing"
    )
    parser.add_argument("--scenario", type=str, default="scenarios/phase5/normal.json")
    parser.add_argument("--episodes", type=int, default=80)
    parser.add_argument("--max-steps", type=int, default=50,
                        help="Max simulation steps per episode")
    parser.add_argument("--update-interval", type=int, default=4,
                        help="Episodes between PPO updates")
    parser.add_argument("--output-dir", type=str, default="runs/learning_nscrpo")
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--actor-lr", type=float, default=3e-4)
    parser.add_argument("--critic-lr", type=float, default=1e-3)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Training] Using device: {device}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario not found: {scenario_path}", file=sys.stderr)
        sys.exit(1)

    # ----- Environment -----
    print(f"[Training] Initializing environment from {scenario_path}...")
    env = PythonSatRoutingEnv(
        scenario_path=scenario_path,
        output_dir=output_dir / "sim_scratch",
        max_steps=args.max_steps,
    )
    init_state, info = env.reset(seed=args.seed)
    state_dim = len(init_state)
    num_edges = len(info["observation"]["links"])
    print(f"[Training] Environment ready: state_dim={state_dim}, num_edges={num_edges}")

    # ----- Model & Trainer -----
    model = NeuroSymbolicActorCritic(
        state_dim=state_dim,
        num_edges=num_edges,
        hidden_dim=args.hidden_dim,
    ).to(device)

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[Training] Model params: {total_params:,} total, {trainable_params:,} trainable")

    trainer = PPOLagrangianTrainer(
        model=model,
        actor_lr=args.actor_lr,
        critic_lr=args.critic_lr,
        device=device,
    )

    best_reward = -float("inf")
    history = []
    training_start = time.time()

    # ----- Header -----
    header = (
        f"{'Ep':>4} | {'Reward':>10} | {'Ctrl':>6} | {'RT':>6} | "
        f"{'μ_ctrl':>8} | {'μ_rt':>8} | {'Steps':>5} | "
        f"{'P.Loss':>8} | {'C.Loss':>8} | {'Served':>10} | {'Rejected':>10}"
    )
    print("\n" + "-" * len(header))
    print(header)
    print("-" * len(header))

    # ----- Training Loop -----
    ep_range = range(1, args.episodes + 1)
    if HAS_TQDM:
        ep_range = tqdm(ep_range, desc="Training", unit="ep")

    for ep in ep_range:
        state, info = env.reset(seed=args.seed + ep)
        ep_reward = 0.0
        ep_ctrl_viol = 0
        ep_rt_viol = 0
        ep_served = 0
        ep_rejected = 0
        steps = 0

        while True:
            state_t = torch.tensor(state, dtype=torch.float32, device=device).unsqueeze(0)
            action, log_prob, v_p, c_c, c_r = model.get_action(state_t, deterministic=False)

            action_np = action.squeeze(0).cpu().numpy()
            lp_val = float(log_prob.item())
            vp_val = float(v_p.item())
            cc_val = float(c_c.item())
            cr_val = float(c_r.item())

            next_state, reward, costs, terminated, truncated, step_info = env.step(action_np)

            # Store transition
            trainer.buffer.states.append(state)
            trainer.buffer.actions.append(action_np)
            trainer.buffer.log_probs.append(lp_val)
            trainer.buffer.rewards.append(reward)
            trainer.buffer.costs_ctrl.append(costs["cost_control"])
            trainer.buffer.costs_rt.append(costs["cost_realtime"])
            trainer.buffer.dones.append(terminated or truncated)
            trainer.buffer.values_primal.append(vp_val)
            trainer.buffer.values_ctrl.append(cc_val)
            trainer.buffer.values_rt.append(cr_val)

            ep_reward += reward
            ep_ctrl_viol += int(costs["cost_control"] > 0)
            ep_rt_viol += int(costs["cost_realtime"] > 0)
            ep_served += step_info.get("delta_served_bulk", 0)
            ep_rejected += step_info.get("delta_rejected_bulk", 0)
            steps += 1
            state = next_state

            if terminated or truncated:
                break

        # PPO update
        loss_p, loss_c = None, None
        if ep % args.update_interval == 0 and len(trainer.buffer) > 0:
            stats = trainer.train_step()
            loss_p = stats.get("loss_policy")
            loss_c = stats.get("loss_critic")
        else:
            stats = {"mu_control": trainer.mu_ctrl, "mu_realtime": trainer.mu_rt}

        record = {
            "episode": ep,
            "reward": ep_reward,
            "ctrl_violations": ep_ctrl_viol,
            "rt_violations": ep_rt_viol,
            "mu_ctrl": float(trainer.mu_ctrl),
            "mu_rt": float(trainer.mu_rt),
            "steps": steps,
            "loss_policy": loss_p,
            "loss_critic": loss_c,
            "total_served_bulk": ep_served,
            "total_rejected_bulk": ep_rejected,
        }
        history.append(record)

        # Log
        lp_str = f"{loss_p:>8.4f}" if loss_p is not None else f"{'—':>8}"
        lc_str = f"{loss_c:>8.4f}" if loss_c is not None else f"{'—':>8}"
        line = (
            f"{ep:>4} | {ep_reward:>10.3f} | {ep_ctrl_viol:>6} | {ep_rt_viol:>6} | "
            f"{trainer.mu_ctrl:>8.4f} | {trainer.mu_rt:>8.4f} | {steps:>5} | "
            f"{lp_str} | {lc_str} | {ep_served:>10} | {ep_rejected:>10}"
        )
        if HAS_TQDM:
            ep_range.set_postfix_str(f"R={ep_reward:.2f} S={steps}")
        else:
            print(line)

        # Save best
        if ep_reward > best_reward:
            best_reward = ep_reward
            trainer.save_checkpoint(output_dir / "best_model.pt", scenario_tag=scenario_path.stem)

    # ----- Wrap up -----
    elapsed = time.time() - training_start
    print("-" * 100)
    print(f"[Training] Completed {args.episodes} episodes in {elapsed:.1f}s")

    trainer.save_checkpoint(output_dir / "final_model.pt", scenario_tag=scenario_path.stem)
    history_path = output_dir / "train_history.json"
    history_path.write_text(json.dumps(history, indent=2))
    print(f"[Training] Checkpoints saved to {output_dir}")
    print(f"[Training] History saved to {history_path}")

    # Summary
    print_summary_table(history)

    # Plots
    if not args.no_plots:
        plot_training_curves(history, output_dir)

    env.close()


if __name__ == "__main__":
    main()

