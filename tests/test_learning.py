"""Unit tests for the learning package (encoder, tree decoder, registry, simpler RL)."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from packet_backend.controller import validate_routes
from packet_backend.learning.encoder import GraphObservationEncoder, NeuroSymbolicTreeDecoder
from packet_backend.learning.registry import CheckpointRegistry
from packet_backend.learning.simpler_rl import SimplerRLPolicy


class TestLearningComponents(unittest.TestCase):
    def setUp(self):
        # Synthetic minimal observation matching ns-3 schema
        self.observation = {
            'time_s': 1.0,
            'nodes': ['SAT0', 'SAT1', 'SAT2', 'GS0'],
            'destinations': [3],
            'non_transit_nodes': [3],
            'mtu_bytes': 1500,
            'qos': {
                'scheduler': 'drr',
                'weights': {'CONTROL': 4, 'REALTIME': 2, 'BULK': 1},
                'quantum_bytes': 1500,
                'targets': {
                    'CONTROL': {'deadline_s': 0.05},
                    'REALTIME': {'deadline_s': 0.1},
                    'BULK': {'min_goodput_bps': 20000},
                }
            },
            'links': [
                {'id': 0, 'a': 0, 'b': 1, 'capacity_bps': 10000000, 'delay_s': 0.01},
                {'id': 1, 'a': 1, 'b': 2, 'capacity_bps': 10000000, 'delay_s': 0.01},
                {'id': 2, 'a': 2, 'b': 3, 'capacity_bps': 2000000, 'delay_s': 0.005},
                {'id': 3, 'a': 0, 'b': 2, 'capacity_bps': 10000000, 'delay_s': 0.025},
            ],
            'queues': [
                {'link_id': 0, 'direction': 0, 'packets': 2, 'bytes': 1600,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 1600, 'arrived_bytes': 1600, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 0, 'direction': 1, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 1, 'direction': 0, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 1, 'direction': 1, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 2, 'direction': 0, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 2, 'direction': 1, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 3, 'direction': 0, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
                {'link_id': 3, 'direction': 1, 'packets': 0, 'bytes': 0,
                 'classes': {'CONTROL': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'REALTIME': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0},
                             'BULK': {'bytes': 0, 'arrived_bytes': 0, 'served_bytes': 0, 'rejected_bytes': 0}}},
            ],
            'active_flows': [
                {'id': 0, 'src': 0, 'dst': 3, 'class_id': 2, 'flow_type': 'BULK', 'rate': 1000000, 'size': 1200, 'deadline_s': None}
            ]
        }

    def test_encoder_produces_valid_vector(self):
        encoder = GraphObservationEncoder(max_links=10, max_flows=5)
        vec = encoder.encode(self.observation)
        self.assertIsInstance(vec, np.ndarray)
        self.assertEqual(len(vec), (10 * 2 * 16) + (5 * 5))
        self.assertFalse(np.isnan(vec).any())

    def test_decoder_guarantees_loop_free_routes(self):
        decoder = NeuroSymbolicTreeDecoder()
        potentials = np.random.uniform(0.0, 1.0, size=(len(self.observation['links']), 3))
        routes = decoder.decode(self.observation, potentials)

        # Must pass strict route validation
        validate_routes(routes, self.observation)

        # Check destination reachability
        for c in range(3):
            # Path from SAT0 must reach GS0 (3)
            self.assertIn((c, 0, 3), routes)
            nxt = routes[c, 0, 3]
            self.assertIn(nxt, [1, 2])

    def test_simpler_rl_policy_execution(self):
        policy = SimplerRLPolicy()
        routes = policy(self.observation)
        validate_routes(routes, self.observation)

    def test_checkpoint_registry_integrity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ckpt_path = Path(tmp_dir) / "test_model.pt"
            ckpt_path.write_bytes(b"dummy_weights_12345")

            manifest = CheckpointRegistry.create_manifest(
                checkpoint_path=ckpt_path,
                architecture="TestModel",
                state_dim=100,
                num_edges=10,
                scenario_compatibility=["phase5"]
            )
            self.assertIn("weight_hash", manifest)

            # Verification should succeed
            verified = CheckpointRegistry.verify_manifest(ckpt_path, scenario_tag="phase5")
            self.assertEqual(verified["weight_hash"], manifest["weight_hash"])

            # Tampering should fail
            ckpt_path.write_bytes(b"tampered_weights")
            with self.assertRaises(ValueError):
                CheckpointRegistry.verify_manifest(ckpt_path)


if __name__ == "__main__":
    unittest.main()

