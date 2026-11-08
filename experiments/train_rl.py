"""
Neuro-Symbolic Constrained Reinforcement Learning (NS-CRPO) Training Pipeline.
Designed for reproducible training on local machines and Kaggle notebooks (CPU/GPU).

Features:
  - Clean formatted telemetry table tracking rewards, steps, violations, and losses
  - Dual Lagrange multiplier adaptation for Control and Realtime QoS constraints
  - Checkpoint saving with manifest hashing (best_model.pt & final_model.pt)
  - Publication-quality training curve visualizations saved to disk & displayed in Kaggle
  - Comprehensive statistical summary table analyzing training convergence
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError as err:
    HAS_TORCH = False
    TORCH_ERR = err

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
if HAS_TORCH:
    from packet_backend.learning.env import SatelliteRoutingEnv
    from packet_backend.learning.models import NeuroSymbolicActorCritic
    from packet_backend.learning.ppo_lagrangian import PPOLagrangianTrainer
    from packet_backend.learning.registry import CheckpointRegistry


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Train Neuro-Symbolic Constrained RL (NS-CRPO) on LEO Satellite Routing"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="scenarios/phase5/normal.json",
        help="Path to scenario JSON configuration",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=40,
        help="Number of training episodes (default: 40)",
    )
    parser.add_argument(
        "--update-interval",
        type=int,
        default=4,
        help="Episodes between PPO policy updates (default: 4)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="runs/learning_nscrpo",
        help="Directory to save checkpoints, manifests, history, and plots",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Execution device: auto, cpu, or cuda (default: auto)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--actor-lr",
        type=float,
        default=3e-4,
        help="Learning rate for actor network (default: 3e-4)",
    )
    parser.add_argument(
        "--critic-lr",
        type=float,
        default=1e-3,
        help="Learning rate for critic networks (default: 1e-3)",
    )
    parser.add_argument(
        "--dual-lr",
        type=float,
        default=0.05,
        help="Learning rate for dual multipliers (default: 0.05)",
    )
    parser.add_argument(
        "--target-ctrl",
        type=float,
        default=0.02,
        help="Control packet violation tolerance (default: 0.02)",
    )
    parser.add_argument(
        "--target-rt",
        type=float,
        default=0.05,
        help="Realtime packet violation tolerance (default: 0.05)",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Disable automatic plot generation",
    )
    return parser.parse_args(argv)


def plot_and_display_metrics(history: List[Dict[str, Any]], output_dir: Path):
    """Generate high-resolution training visual curves and render in Kaggle/Jupyter."""
    if not HAS_MATPLOTLIB or not history:
        return

    episodes = [h["episode"] for h in history]
    rewards = [h["reward"] for h in history]
    ctrl_viols = [h["ctrl_violations"] for h in history]
    rt_viols = [h["rt_violations"] for h in history]
    mu_ctrl = [h["mu_ctrl"] for h in history]
    mu_rt = [h["mu_rt"] for h in history]
    steps = [h.get("steps", 0) for h in history]
    served_bulk_mb = [h.get("served_bulk_bytes", 0) / (1024 * 1024) for h in history]
    rejected_bulk_mb = [h.get("rejected_bulk_bytes", 0) / (1024 * 1024) for h in history]

    # Filtered loss points
    p_losses = [(h["episode"], h["loss_policy"]) for h in history if h.get("loss_policy") is not None]
    c_losses = [(h["episode"], h["loss_critic"]) for h in history if h.get("loss_critic") is not None]

    fig, axes = plt.subplots(3, 2, figsize=(15, 13))
    fig.suptitle(
        "Neuro-Symbolic Constrained RL (NS-CRPO) — LEO Satellite QoS Routing",
        fontsize=14,
        fontweight="bold",
        y=0.995,
    )

    # 1. Bulk Throughput Return
    ax1 = axes[0, 0]
    ax1.plot(episodes, rewards, color="#1f77b4", marker="o", markersize=3, alpha=0.6, label="Episode Return")
    if len(rewards) >= 5:
        w = min(10, max(3, len(rewards) // 4))
        smoothed = np.convolve(rewards, np.ones(w) / w, mode="valid")
        ax1.plot(episodes[w - 1:], smoothed, color="#d62728", linewidth=2.0, label=f"Moving Avg (w={w})")
    ax1.set_xlabel("Episode")
    ax1.set_ylabel("Bulk Return")
    ax1.set_title("Primal Objective: Bulk Throughput Return", fontweight="semibold")
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper left")

    # 2. QoS Constraint Violations
    ax2 = axes[0, 1]
    ax2.plot(episodes, ctrl_viols, color="#d62728", marker="s", markersize=3, label="Control Drops")
    ax2.plot(episodes, rt_viols, color="#ff7f0e", marker="^", markersize=3, label="Realtime Drops")
    ax2.set_xlabel("Episode")
    ax2.set_ylabel("Violations Count")
    ax2.set_title("Dual Constraints: Urgent Class Drops", fontweight="semibold")
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.legend(loc="upper right")

    # 3. Lagrange Multipliers Convergence
    ax3 = axes[1, 0]
    ax3.plot(episodes, mu_ctrl, color="#d62728", linewidth=2.0, label="μ_control")
    ax3.plot(episodes, mu_rt, color="#9467bd", linewidth=2.0, label="μ_realtime")
    ax3.set_xlabel("Episode")
    ax3.set_ylabel("Multiplier Value")
    ax3.set_title("Lagrange Multipliers (Dual Variables)", fontweight="semibold")
    ax3.grid(True, linestyle="--", alpha=0.4)
    ax3.legend(loc="upper left")

    # 4. PPO Loss Progression
    ax4 = axes[1, 1]
    if p_losses:
        ax4.plot([x[0] for x in p_losses], [x[1] for x in p_losses], color="#2ca02c", marker="o", label="Policy Loss")
    if c_losses:
        ax4.plot([x[0] for x in c_losses], [x[1] for x in c_losses], color="#17becf", marker="x", label="Critic MSE Loss")
    ax4.set_xlabel("Episode")
    ax4.set_ylabel("Loss")
    ax4.set_title("PPO-Clip & Value Losses", fontweight="semibold")
    ax4.grid(True, linestyle="--", alpha=0.4)
    ax4.legend(loc="upper right")

    # 5. Bulk Delivered vs Dropped Volume
    ax5 = axes[2, 0]
    ax5.plot(episodes, served_bulk_mb, color="#2ca02c", linewidth=1.8, label="Delivered Bulk (MB)")
    if any(m > 0 for m in rejected_bulk_mb):
        ax5.plot(episodes, rejected_bulk_mb, color="#d62728", linewidth=1.8, label="Dropped Bulk (MB)")
    ax5.set_xlabel("Episode")
    ax5.set_ylabel("Megabytes (MB)")
    ax5.set_title("Total Bulk Traffic Volume", fontweight="semibold")
    ax5.grid(True, linestyle="--", alpha=0.4)
    ax5.legend(loc="upper left")

    # 6. Horizon Steps per Episode
    ax6 = axes[2, 1]
    ax6.bar(episodes, steps, color="#4b6584", alpha=0.75, width=0.6)
    ax6.set_xlabel("Episode")
    ax6.set_ylabel("Simulation Steps")
    ax6.set_title("Trajectory Length per Episode", fontweight="semibold")
    ax6.grid(True, linestyle="--", alpha=0.4, axis="y")

    plt.tight_layout()
    chart_path = output_dir / "training_curves.png"
    fig.savefig(chart_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"\n[Visuals] Successfully generated and saved training curves to {chart_path}")

    # Display directly in Kaggle/Jupyter notebook if running interactively
    try:
        from IPython.display import Image, display
        display(Image(filename=str(chart_path)))
    except Exception:
        pass


def display_performance_summary(history: List[Dict[str, Any]], best_reward: float, output_dir: Path):
    """Print an executive benchmark table segmenting training into performance quartiles."""
    if not history:
        return

    n = len(history)
    rewards = [h["reward"] for h in history]
    ctrl_v = [h["ctrl_violations"] for h in history]
    rt_v = [h["rt_violations"] for h in history]
    steps = [h.get("steps", 0) for h in history]
    served_mb = [h.get("served_bulk_bytes", 0) / (1024 * 1024) for h in history]

    # Divide into 4 quarters
    q = max(1, n // 4)
    q1 = history[:q]
    q2 = history[q:2*q]
    q3 = history[2*q:3*q]
    q4 = history[3*q:]

    def q_avg(quart, key):
        if not quart:
            return 0.0
        return float(np.mean([item.get(key, 0.0) for item in quart]))

    def q_avg_mb(quart):
        if not quart:
            return 0.0
        return float(np.mean([item.get("served_bulk_bytes", 0) / (1024 * 1024) for item in quart]))

    print("\n" + "=" * 88)
    print("                      NS-CRPO TRAINING CONVERGENCE REPORT")
    print("=" * 88)
    print(f"{'Performance Metric':<32} | {'Q1 (Init)':>10} | {'Q2':>10} | {'Q3':>10} | {'Q4 (Final)':>10}")
    print("-" * 88)
    print(f"{'Average Bulk Return':<32} | {q_avg(q1, 'reward'):>10.2f} | {q_avg(q2, 'reward'):>10.2f} | {q_avg(q3, 'reward'):>10.2f} | {q_avg(q4, 'reward'):>10.2f}")
    print(f"{'Average Control Violations':<32} | {q_avg(q1, 'ctrl_violations'):>10.2f} | {q_avg(q2, 'ctrl_violations'):>10.2f} | {q_avg(q3, 'ctrl_violations'):>10.2f} | {q_avg(q4, 'ctrl_violations'):>10.2f}")
    print(f"{'Average Realtime Violations':<32} | {q_avg(q1, 'rt_violations'):>10.2f} | {q_avg(q2, 'rt_violations'):>10.2f} | {q_avg(q3, 'rt_violations'):>10.2f} | {q_avg(q4, 'rt_violations'):>10.2f}")
    print(f"{'Delivered Bulk Volume (MB)':<32} | {q_avg_mb(q1):>10.2f} | {q_avg_mb(q2):>10.2f} | {q_avg_mb(q3):>10.2f} | {q_avg_mb(q4):>10.2f}")
    print(f"{'Average Steps / Episode':<32} | {q_avg(q1, 'steps'):>10.1f} | {q_avg(q2, 'steps'):>10.1f} | {q_avg(q3, 'steps'):>10.1f} | {q_avg(q4, 'steps'):>10.1f}")
    print("-" * 88)
    print(f"{'Peak Bulk Return Achieved':<32} | {best_reward:>10.2f}")
    print(f"{'Final Control Multiplier (μ_ctrl)':<32} | {history[-1]['mu_ctrl']:>10.4f}")
    print(f"{'Final Realtime Multiplier (μ_rt)':<32} | {history[-1]['mu_rt']:>10.4f}")
    print(f"{'Best Model Saved Path':<32} | {str(output_dir / 'best_model.pt'):>10}")
    print("=" * 88 + "\n")


def train(
    scenario: str = "scenarios/phase5/normal.json",
    episodes: int = 40,
    update_interval: int = 4,
    output_dir: str = "runs/learning_nscrpo",
    device: str = "auto",
    seed: int = 42,
    actor_lr: float = 3e-4,
    critic_lr: float = 1e-3,
    dual_lr: float = 0.05,
    target_ctrl: float = 0.02,
    target_rt: float = 0.05,
    no_plots: bool = False,
):
    """Programmatic entry point for training on Kaggle notebook or CLI."""
    if not HAS_TORCH:
        print(f"Error: Missing PyTorch dependencies: {TORCH_ERR}", file=sys.stderr)
        sys.exit(1)

    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    # Resolve device
    if device == "auto":
        exec_device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        exec_device = device
    print(f"[Training] Using execution device: {exec_device}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    scenario_file = Path(scenario)
    if not scenario_file.exists():
        raise FileNotFoundError(f"Scenario configuration not found: {scenario_file}")

    # 1. Initialize environment
    print(f"[Training] Bootstrapping SatelliteRoutingEnv with scenario: {scenario_file} ...")
    env = SatelliteRoutingEnv(
        scenario_path=scenario_file,
        output_dir=out_path / "sim_scratch",
    )
    init_state, info = env.reset(seed=seed)
    state_dim = len(init_state)
    num_edges = len(info["observation"]["links"])
    num_flows = len(info["observation"].get("active_flows", []))

    print(f"[Training] Environment initialized successfully:")
    print(f"           - State Dimension : {state_dim}")
    print(f"           - Link Topology   : {num_edges} bidirectional ISL/ground links")
    print(f"           - Active Flows    : {num_flows} configured QoS traffic flows")

    # 2. Initialize Model & PPO-Lagrangian Trainer
    model = NeuroSymbolicActorCritic(
        state_dim=state_dim,
        num_edges=num_edges,
    ).to(exec_device)

    total_params = sum(p.numel() for p in model.parameters())
    print(f"           - Model Capacity  : {total_params:,} parameters")

    trainer = PPOLagrangianTrainer(
        model=model,
        actor_lr=actor_lr,
        critic_lr=critic_lr,
        dual_lr=dual_lr,
        target_ctrl_violation=target_ctrl,
        target_rt_violation=target_rt,
        device=exec_device,
    )

    best_reward = -float("inf")
    history = []
    start_wall_time = time.time()

    # 3. Training Loop Header
    header = (
        f"{'Ep':>4} | {'Bulk Return':>11} | {'Steps':>5} | "
        f"{'Ctrl Viol':>9} | {'RT Viol':>7} | "
        f"{'μ_ctrl':>7} | {'μ_rt':>7} | "
        f"{'P.Loss':>8} | {'C.Loss':>8} | {'Bulk (MB)':>9}"
    )
    print("\n" + "-" * len(header))
    print(header)
    print("-" * len(header))

    # 4. Episode Execution
    for ep in range(1, episodes + 1):
        state, info = env.reset(seed=seed + ep)
        ep_reward = 0.0
        ep_ctrl_violations = 0
        ep_rt_violations = 0
        ep_served_bulk_bytes = 0
        ep_rejected_bulk_bytes = 0
        steps = 0

        while True:
            state_tensor = torch.tensor(state, dtype=torch.float32, device=exec_device).unsqueeze(0)
            action, log_prob, v_p, c_c, c_r = model.get_action(state_tensor, deterministic=False)

            action_np = action.squeeze(0).cpu().numpy()
            log_prob_val = float(log_prob.item())
            vp_val = float(v_p.item())
            cc_val = float(c_c.item())
            cr_val = float(c_r.item())

            next_state, reward, costs, terminated, truncated, step_info = env.step(action_np)

            # Accumulate experience in rollout buffer
            trainer.buffer.states.append(state)
            trainer.buffer.actions.append(action_np)
            trainer.buffer.log_probs.append(log_prob_val)
            trainer.buffer.rewards.append(reward)
            trainer.buffer.costs_ctrl.append(costs["cost_control"])
            trainer.buffer.costs_rt.append(costs["cost_realtime"])
            trainer.buffer.dones.append(terminated or truncated)
            trainer.buffer.values_primal.append(vp_val)
            trainer.buffer.values_ctrl.append(cc_val)
            trainer.buffer.values_rt.append(cr_val)

            ep_reward += reward
            ep_ctrl_violations += int(costs["cost_control"] > 0)
            ep_rt_violations += int(costs["cost_realtime"] > 0)
            ep_served_bulk_bytes += step_info.get("delta_served_bulk", 0)
            ep_rejected_bulk_bytes += step_info.get("delta_rejected_bulk", 0)
            steps += 1
            state = next_state

            if terminated or truncated:
                break

        # 5. Periodic PPO Update
        loss_p, loss_c = None, None
        if ep % update_interval == 0 and len(trainer.buffer.rewards) > 0:
            stats = trainer.train_step()
            loss_p = stats.get("loss_policy")
            loss_c = stats.get("loss_critic")
        else:
            stats = {
                "mu_control": trainer.mu_ctrl,
                "mu_realtime": trainer.mu_rt,
            }

        # 6. Record Episode Statistics
        record = {
            "episode": ep,
            "reward": float(ep_reward),
            "steps": steps,
            "ctrl_violations": ep_ctrl_violations,
            "rt_violations": ep_rt_violations,
            "mu_ctrl": float(trainer.mu_ctrl),
            "mu_rt": float(trainer.mu_rt),
            "loss_policy": loss_p,
            "loss_critic": loss_c,
            "served_bulk_bytes": ep_served_bulk_bytes,
            "rejected_bulk_bytes": ep_rejected_bulk_bytes,
        }
        history.append(record)

        # 7. Print Telemetry Row
        lp_str = f"{loss_p:>8.4f}" if loss_p is not None else f"{'—':>8}"
        lc_str = f"{loss_c:>8.4f}" if loss_c is not None else f"{'—':>8}"
        bulk_mb_str = f"{ep_served_bulk_bytes / (1024 * 1024):>9.2f}"

        print(
            f"{ep:>4} | {ep_reward:>11.2f} | {steps:>5} | "
            f"{ep_ctrl_violations:>9} | {ep_rt_violations:>7} | "
            f"{trainer.mu_ctrl:>7.3f} | {trainer.mu_rt:>7.3f} | "
            f"{lp_str} | {lc_str} | {bulk_mb_str}"
        )

        # 8. Checkpoint Best Performing Model
        if ep_reward > best_reward:
            best_reward = ep_reward
            trainer.save_checkpoint(out_path / "best_model.pt", scenario_tag=scenario_file.stem)

    # 9. Final Checkpoint and Artifacts
    trainer.save_checkpoint(out_path / "final_model.pt", scenario_file.stem)
    history_file = out_path / "train_history.json"
    history_file.write_text(json.dumps(history, indent=2))

    total_duration = time.time() - start_wall_time
    print("-" * len(header))
    print(f"[Training] Completed {episodes} episodes in {total_duration:.1f} seconds.")
    print(f"[Training] Checkpoints successfully registered in: {out_path}")
    print(f"[Training] History logs exported to: {history_file}")

    # 10. Summary and Plots
    display_performance_summary(history, best_reward, out_path)

    if not no_plots:
        plot_and_display_metrics(history, out_path)

    env.close()
    return history


def main():
    args = parse_args()
    train(
        scenario=args.scenario,
        episodes=args.episodes,
        update_interval=args.update_interval,
        output_dir=args.output_dir,
        device=args.device,
        seed=args.seed,
        actor_lr=args.actor_lr,
        critic_lr=args.critic_lr,
        dual_lr=args.dual_lr,
        target_ctrl=args.target_ctrl,
        target_rt=args.target_rt,
        no_plots=args.no_plots,
    )


if __name__ == "__main__":
    main()
