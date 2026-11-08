"""Policy adapter exposing trained learned models through the standard controller interface."""
from copy import deepcopy
from pathlib import Path
import numpy as np

from packet_backend.controller import congestion_routes, validate_routes
from packet_backend.learning.encoder import GraphObservationEncoder, NeuroSymbolicTreeDecoder
from packet_backend.learning.registry import CheckpointRegistry
from packet_backend.qos import CLASSES

try:
    import torch
    from packet_backend.learning.models import NeuroSymbolicActorCritic
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


class LearnedPolicy:
    """Callable policy wrapper for offline-trained Neuro-Symbolic Constrained RL models.

    Adheres strictly to the packet_backend.controller interface.
    """

    def __init__(self,
                 checkpoint_path: Path | str,
                 prediction_config: dict | None = None,
                 orbital_forecaster = None,
                 device: str = "cpu",
                 strict: bool = True,
                 name: str | None = None):
        self.checkpoint_path = Path(checkpoint_path)
        self.prediction_config = prediction_config or {}
        self.orbital = orbital_forecaster
        self.device = device
        self.strict = strict
        self.name = name or f"learned.nscrpo.{self.checkpoint_path.stem}"
        self.last_diagnostics = {}

        # Verify manifest
        self.manifest = CheckpointRegistry.verify_manifest(self.checkpoint_path)

        # Initialize encoder and decoder
        self.encoder = GraphObservationEncoder()
        self.decoder = NeuroSymbolicTreeDecoder()

        if not HAS_TORCH:
            raise ImportError("PyTorch is required to run LearnedPolicy inference.")

        # Load model weights
        state_dim = self.manifest["state_dim"]
        num_edges = self.manifest["num_edges"]
        self.model = NeuroSymbolicActorCritic(state_dim=state_dim, num_edges=num_edges).to(self.device)
        state_dict = torch.load(self.checkpoint_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model.eval()  # Strictly frozen evaluation mode

        param_count = sum(p.numel() for p in self.model.parameters())
        print(f"[NS-CRPO] Checkpoint loaded successfully:")
        print(f"         - Path        : {self.checkpoint_path}")
        print(f"         - SHA-256     : {self.manifest.get('weight_hash')}")
        print(f"         - Architecture: {self.manifest.get('architecture', type(self.model).__name__)}")
        print(f"         - Parameters  : {param_count:,}")
        print(f"         - Status      : Verified & Frozen (strict={self.strict})")

    def reset(self):
        self.decoder.reset()
        self.last_diagnostics.clear()

    def __call__(self, observation: dict) -> dict[tuple[int, int, int], int]:
        try:
            # 1. Causal orbital forecast if available
            orbital_forecasts = {}
            if self.orbital:
                raw_forecasts = self.orbital.predict(observation)
                orbital_forecasts = {f['link_id']: f for f in raw_forecasts}

            # 2. Encode state into normalized tensor
            flat_state = self.encoder.encode(observation, orbital_forecasts)
            state_tensor = torch.from_numpy(flat_state).unsqueeze(0).to(self.device)

            # 3. Deterministic policy forward pass
            with torch.no_grad():
                action, _, v_primal, c_ctrl, c_rt = self.model.get_action(state_tensor, deterministic=True)
                potentials_flat = action.squeeze(0).cpu().numpy()
                # Reshape to (num_edges, 3)
                num_edges = len(observation['links'])
                potentials = potentials_flat[:num_edges * 3].reshape((num_edges, 3))

            # 4. Neuro-symbolic tree decode (guaranteed loop-free DAG)
            routes = self.decoder.decode(observation, potentials, orbital_forecasts)

            # 5. Record diagnostics
            self.last_diagnostics = {
                "v_primal": float(v_primal.item()),
                "cost_control_est": float(c_ctrl.item()),
                "cost_realtime_est": float(c_rt.item()),
                "model_hash": self.manifest["weight_hash"][:12],
                "fallback_triggered": False,
            }

            # 6. Safety validation check
            validate_routes(routes, observation)
            return routes

        except Exception as exc:
            if self.strict:
                raise RuntimeError(f"NS-CRPO inference failed: {exc}") from exc
            # Documented heuristic fallback if any unexpected condition occurs
            fallback_routes = congestion_routes(observation)
            expanded_fallback = {(c, s, d): nxt for c in range(3) for (s, d), nxt in fallback_routes.items()}
            self.last_diagnostics = {
                "fallback_triggered": True,
                "fallback_reason": str(exc),
            }
            return expanded_fallback

