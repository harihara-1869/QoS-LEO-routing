"""Unit tests for Phase 7 policy evaluation and ablation runner."""

import json
import tempfile
import unittest
from pathlib import Path

from experiments.evaluate import POLICIES, run_ablation_study, run_full_evaluation


class EvaluationUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.scenario = self.repo_root / "scenarios/phase4/normal.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ablation_study_structure(self):
        """Verify ablation configurations and metric presence."""
        ablations = run_ablation_study(self.scenario, self.output_dir / "ablations")
        self.assertIn("full_predictive", ablations)
        self.assertIn("ablation_no_queue_forecast", ablations)
        self.assertIn("ablation_no_lifetime", ablations)
        self.assertIn("ablation_no_safeguards", ablations)

        for name, data in ablations.items():
            self.assertIn("delivered", data)
            self.assertIn("route_changes", data)
            self.assertIn("realtime_on_time_pct", data)
            self.assertIn("control_on_time_pct", data)

        # Full predictive should have higher Realtime on-time rate than ablations
        full_rt = ablations["full_predictive"]["realtime_on_time_pct"]
        no_lifetime_rt = ablations["ablation_no_lifetime"]["realtime_on_time_pct"]
        self.assertGreater(full_rt, no_lifetime_rt)

    def test_full_evaluation_json_export(self):
        """Verify evaluation_results.json schema and observations."""
        results = run_full_evaluation([self.scenario], self.output_dir)
        
        self.assertIn("normal", results["scenarios"])
        scenario_results = results["scenarios"]["normal"]
        for policy in POLICIES:
            self.assertIn(policy, scenario_results)
            self.assertIn("delivered", scenario_results[policy])
            self.assertIn("qos", scenario_results[policy])

        # Verify summary observations exist and include unfavorable outcomes
        obs_text = " ".join(results["summary_observations"])
        self.assertIn("UNFAVORABLE OUTCOME", obs_text)
        self.assertIn("Control 50ms", obs_text)

        out_json = self.output_dir / "evaluation_results.json"
        self.assertTrue(out_json.exists())
        loaded = json.loads(out_json.read_text())
        self.assertIn("scenarios", loaded)


if __name__ == "__main__":
    unittest.main()
