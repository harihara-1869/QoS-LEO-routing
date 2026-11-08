"""Actor-Critic neural networks for Neuro-Symbolic Constrained RL."""
from typing import Tuple

try:
    import torch
    import torch.nn as nn
    from torch.distributions import Normal
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


if HAS_TORCH:
    class NeuroSymbolicActorCritic(nn.Module):
        """Actor-Critic network supporting primal-dual constrained optimization.

        Outputs continuous edge potential perturbations and estimates both
        primal value (Bulk return) and dual costs (Control and Realtime violations).
        """

        def __init__(self,
                     state_dim: int,
                     num_edges: int = 388,
                     num_classes: int = 3,
                     hidden_dim: int = 256):
            super().__init__()
            self.num_edges = num_edges
            self.num_classes = num_classes
            self.action_dim = num_edges * num_classes

            # Shared feature backbone
            self.backbone = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.LeakyReLU(0.1),
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.LayerNorm(hidden_dim // 2),
                nn.LeakyReLU(0.1),
            )

            # Actor head: outputs distribution mean for potential perturbations
            self.actor_mean = nn.Sequential(
                nn.Linear(hidden_dim // 2, self.action_dim),
                nn.Sigmoid(),  # Bound potentials to [0, 1]
            )
            # Log standard deviation parameter
            self.actor_log_std = nn.Parameter(torch.full((self.action_dim,), -1.0))

            # Primal Critic: estimates expected long-term Bulk throughput
            self.critic_primal = nn.Sequential(
                nn.Linear(hidden_dim // 2, 64),
                nn.LeakyReLU(0.1),
                nn.Linear(64, 1),
            )

            # Dual Cost Critics: estimate expected Control and Realtime violations
            self.critic_cost_control = nn.Sequential(
                nn.Linear(hidden_dim // 2, 64),
                nn.LeakyReLU(0.1),
                nn.Linear(64, 1),
            )
            self.critic_cost_realtime = nn.Sequential(
                nn.Linear(hidden_dim // 2, 64),
                nn.LeakyReLU(0.1),
                nn.Linear(64, 1),
            )

        def forward(self, state: torch.Tensor):
            features = self.backbone(state)
            action_mean = self.actor_mean(features)
            action_std = torch.exp(torch.clamp(self.actor_log_std, -2.0, 0.5))

            v_primal = self.critic_primal(features)
            c_control = self.critic_cost_control(features)
            c_realtime = self.critic_cost_realtime(features)

            return action_mean, action_std, v_primal, c_control, c_realtime

        def get_action(self, state: torch.Tensor, deterministic: bool = False):
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

        def evaluate(self, states: torch.Tensor, actions: torch.Tensor):
            features = self.backbone(states)
            mean = self.actor_mean(features)
            std = torch.exp(torch.clamp(self.actor_log_std, -2.0, 0.5))
            dist = Normal(mean, std)

            log_probs = dist.log_prob(actions).sum(dim=-1)
            entropy = dist.entropy().sum(dim=-1)

            # Detach features for critic updates to decouple graph backward passes
            feat_detach = features.detach()
            v_primal = self.critic_primal(feat_detach).squeeze(-1)
            c_control = self.critic_cost_control(feat_detach).squeeze(-1)
            c_realtime = self.critic_cost_realtime(feat_detach).squeeze(-1)

            return log_probs, entropy, v_primal, c_control, c_realtime

else:
    class NeuroSymbolicActorCritic:
        def __init__(self, *args, **kwargs):
            raise ImportError("PyTorch is required to instantiate NeuroSymbolicActorCritic. Install via `pip install -r requirements/learning.txt`.")

