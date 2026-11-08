"""Checkpoint registry and manifest verification for learned policies."""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict


SCHEMA_VERSION = "leo_rl_v1"


def compute_file_hash(path: Path | str) -> str:
    path = Path(path)
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class CheckpointRegistry:
    """Manages versioned, hashed checkpoints and validates compatibility."""

    @staticmethod
    def create_manifest(checkpoint_path: Path | str,
                        architecture: str,
                        state_dim: int,
                        num_edges: int,
                        scenario_compatibility: list[str] | None = None,
                        hyperparameters: Dict[str, Any] | None = None,
                        weights_mode: str = "frozen") -> Dict[str, Any]:
        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint file not found: {checkpoint_path}")

        weight_hash = compute_file_hash(checkpoint_path)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "architecture": architecture,
            "weight_hash": weight_hash,
            "weight_file": checkpoint_path.name,
            "weights_mode": weights_mode,  # strictly 'frozen' for scientific evaluation
            "state_dim": state_dim,
            "num_edges": num_edges,
            "encoder_version": "v1_compact_graph",
            "action_space": "neuro_symbolic_potential_v1",
            "scenario_compatibility": scenario_compatibility or ["walker_200_satellites", "phase5"],
            "hyperparameters": hyperparameters or {},
        }

        manifest_path = checkpoint_path.parent / f"{checkpoint_path.stem}.manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        return manifest

    @staticmethod
    def verify_manifest(checkpoint_path: Path | str, scenario_tag: str | None = None) -> Dict[str, Any]:
        checkpoint_path = Path(checkpoint_path)
        manifest_path = checkpoint_path.parent / f"{checkpoint_path.stem}.manifest.json"

        if not manifest_path.exists():
            raise ValueError(f"Missing manifest for checkpoint: {checkpoint_path}")

        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Incompatible checkpoint schema: {manifest.get('schema_version')}")

        # Verify hash integrity
        current_hash = compute_file_hash(checkpoint_path)
        if current_hash != manifest.get("weight_hash"):
            raise ValueError(f"Checkpoint integrity check failed! Expected {manifest.get('weight_hash')}, got {current_hash}")

        # Check weights mode
        if manifest.get("weights_mode") != "frozen":
            raise ValueError(f"Invalid weights mode for evaluation: {manifest.get('weights_mode')}. Must be 'frozen'.")

        # Check scenario compatibility
        if scenario_tag:
            compat = manifest.get("scenario_compatibility", [])
            if compat and not any(tag in scenario_tag for tag in compat):
                raise ValueError(f"Checkpoint is not compatible with scenario {scenario_tag}. Allowed: {compat}")

        return manifest

