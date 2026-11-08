"""Standalone script to train Neuro-Symbolic Constrained RL (NS-CRPO)."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

try:
    import torch
    from packet_backend.learning.env import SatelliteRoutingEnv
    from packet_backend.learning.models import NeuroSymbolicActorCritic
    from packet_backend.learning.ppo_lagrangian import PPOLagrangianTrainer
    HAS_DEPS = True
except ImportError as err:
    HAS_DEPS = False
    IMPORT_ERR = err


def parse_args():
    parser = argparse.ArgumentParser(description="Train Neuro-Symbolic Constrained RL on LEO scenarios")
    parser.add_argument("--scenario", type=str, default="scenarios/phase5/normal.json", help="Scenario JSON path")
    parser.add_argument("--episodes", type=int, default=30, help="Number of training episodes")
    parser.add_argument("--update-interval", type=int, default=5, help="Episodes between PPO policy updates")
    parser.add_argument("--output-dir", type=str, default="runs/learning", help="Output directory for logs and models")
    parser.add_argument("--device", type=str, default="auto", help="Execution device: auto, cpu, or cuda")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


def main():
    if not HAS_DEPS:
        print(f"Error: Missing training dependencies: {IMPORT_ERR}", file=sys.stderr)
        print("Please install PyTorch: pip install -r requirements/learning.txt", file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    # Determine device
    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    print(f"[Training] Using execution device: {device}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize environment
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file not found: {scenario_path}", file=sys.stderr)
        sys.exit(1)

    env = SatelliteRoutingEnv(scenario_path=scenario_path, output_dir=output_dir / "sim_scratch")
    init_state, info = env.reset(seed=args.seed)
    state_dim = len(init_state)
    num_edges = len(info['observation']['links'])

    print(f"[Training] Environment initialized: state_dim={state_dim}, num_edges={num_edges}")

    # 2. Initialize Actor-Critic and Trainer
    model = NeuroSymbolicActorCritic(state_dim=state_dim, num_edges=num_edges).to(device)
    trainer = PPOLagrangianTrainer(model=model, device=device)

    best_reward = -float('inf')
    history = []

    print("-" * 75)
    print(f"{'Ep':<5} | {'Bulk Reward':<12} | {'Ctrl Viol':<10} | {'RT Viol':<10} | {'mu_ctrl':<8} | {'mu_rt':<8}")
    print("-" * 75)

    for ep in range(1, args.episodes + 1):
        state, info = env.reset(seed=args.seed + ep)
        ep_reward = 0.0
        ep_ctrl_violations = 0
        ep_rt_violations = 0
        steps = 0

        while True:
            state_tensor = torch.tensor(state, dtype=torch.float32, device=device).unsqueeze(0)
            action, log_prob, v_p, c_c, c_r = model.get_action(state_tensor, deterministic=False)

            action_np = action.squeeze(0).cpu().numpy()
            log_prob_val = float(log_prob.item())
            vp_val = float(v_p.item())
            cc_val = float(c_c.item())
            cr_val = float(c_r.item())

            next_state, reward, costs, terminated, truncated, _ = env.step(action_np)

            # Store in rollout buffer
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
            steps += 1
            state = next_state

            if terminated or truncated:
                break

        # Periodic PPO update
        if ep % args.update_interval == 0:
            stats = trainer.train_step()
        else:
            stats = {
                "mu_control": trainer.mu_ctrl,
                "mu_realtime": trainer.mu_rt,
            }

        history.append({
            "episode": ep,
            "reward": ep_reward,
            "ctrl_violations": ep_ctrl_violations,
            "rt_violations": ep_rt_violations,
            "mu_ctrl": stats.get("mu_control", 0.0),
            "mu_rt": stats.get("mu_realtime", 0.0),
        })

        print(f"{ep:<5} | {ep_reward:<12.2f} | {ep_ctrl_violations:<10} | {ep_rt_violations:<10} | {trainer.mu_ctrl:<8.3f} | {trainer.mu_rt:<8.3f}")

        # Save best model
        if ep_reward > best_reward:
            best_reward = ep_reward
            trainer.save_checkpoint(output_dir / "best_model.pt", scenario_tag=scenario_path.stem)

    # Save final model
    trainer.save_checkpoint(output_dir / "final_model.pt", scenario_tag=scenario_path.stem)
    (output_dir / "train_history.json").write_text(json.dumps(history, indent=2))
    print("-" * 75)
    print(f"[Training] Completed! Saved checkpoints to {output_dir}")


if __name__ == "__main__":
    main()

