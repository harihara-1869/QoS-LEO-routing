"""Dashboard data semantics, API persistence and observer isolation."""

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from dashboard.data import (
    Metrics,
    check_limits,
    packet_metrics,
    validate_bundle,
    Geometry,
)
from constellation.omm import generate_omm_csv
from packet_backend.build import ROOT
from experiments.run import run


class DashboardMetricTests(unittest.TestCase):
    def test_live_deadline_outcomes_balance_and_censor_pending(self):
        flows = [dict(id=1, flow_type="CONTROL", deadline_s=0.05)]
        model = Metrics(flows)
        for pid, t in [(1, 0), (2, 0.01), (3, 0.09)]:
            model.event(dict(kind="udp_created", item=1, a=pid, time_s=t, value=100))
        model.event(dict(kind="udp_delivered", item=1, a=1, time_s=0.02, value=100))
        model.event(dict(kind="udp_dropped", item=1, a=2, time_s=0.03, value=100))
        m = model.at(0.1)
        c = m["classes"]["CONTROL"]
        self.assertEqual(
            (m["generated"], m["delivered"], m["dropped"], m["in_flight"]), (3, 1, 1, 1)
        )
        self.assertEqual(c["deadline_success"], 0.5)
        self.assertAlmostEqual(m["delay_p95_s"], 0.02)
        self.assertAlmostEqual(
            model.at(0.2)["classes"]["CONTROL"]["deadline_success"], 1 / 3
        )

    def test_replay_does_not_count_future_delivery_or_tcp_as_datagrams(self):
        packets = [
            dict(
                flow_id=1, size_bytes=100, created_s=0, ended_s=0.2, status="delivered"
            )
        ]
        m = packet_metrics(
            packets, {1: dict(flow_type="BULK", deadline_s=None)}, 0.1, tcp_bytes=50
        )
        self.assertEqual(m["delivered"], 0)
        self.assertEqual(m["in_flight"], 1)
        self.assertEqual(m["delivered_bytes"], 50)
        self.assertEqual(m["classes"]["BULK"]["goodput_bps"], 4000)
        self.assertIsNone(m["delay_p95_s"])

    def test_preview_resource_limits(self):
        c = json.loads((ROOT / "scenarios/phase5/normal.json").read_text())
        self.assertEqual(check_limits(c)["satellites"], 200)
        c["constellation"]["n_planes"] = 10000
        with self.assertRaises(ValueError):
            check_limits(c)

    def test_bundled_demo_is_real_and_conserves_accounting(self):
        bundle = json.loads((ROOT / "web/public/data/demo.json").read_text())
        self.assertEqual(bundle["frame"], "ECEF")
        self.assertTrue(bundle["result_hash"])
        self.assertEqual(len(bundle["nodes"]), 204)
        for frame in bundle["frames"]:
            m = frame["metrics"]
            self.assertEqual(
                m["generated"], m["delivered"] + m["dropped"] + m["in_flight"]
            )
        self.assertEqual(bundle["frames"][-1]["metrics"]["generated"], 6225)

    def test_saved_class_metrics_match_final_authoritative_summaries(self):
        for name in ("demo", "baseline"):
            bundle = json.loads((ROOT / f"web/public/data/{name}.json").read_text())
            validate_bundle(bundle)
            for kind, m in bundle["frames"][-1]["metrics"]["classes"].items():
                q = bundle["summary"]["classes"][kind]
                self.assertEqual(m["generated"], q["udp_generated"])
                self.assertEqual(m["delivered"], q["udp_delivered"])
                self.assertEqual(m["delay_p95_s"], q["delay_p95_s"])
                self.assertEqual(m["deadline_success"], q["deadline"]["success_ratio"])

    def test_ground_position_is_ecef_and_preserves_station_geography(self):
        config = json.loads((ROOT / "scenarios/phase5/normal.json").read_text())
        config["constellation"].update(n_planes=1, sats_per_plane=2)
        config["ground_stations"] = [["GS_TEST", 0, 90, 0]]
        with tempfile.TemporaryDirectory() as temp:
            csv = Path(temp) / "constellation.csv"
            generate_omm_csv(str(csv), **config["constellation"], epoch=config["epoch"])
            geometry = Geometry(config, csv)
            for time in (0, 100):
                x, y, z = geometry.positions(time)[-1]
                self.assertAlmostEqual(x, 0, places=3)
                self.assertAlmostEqual(y, 6378.137, places=3)
                self.assertAlmostEqual(z, 0, places=3)


@unittest.skipUnless(
    (ROOT / ".venv-ns3/bin/python").exists()
    or __import__("os").environ.get("LEO_NS3_PYTHON"),
    "Install pinned packet engine",
)
class DashboardEngineTests(unittest.TestCase):
    def test_observer_preserves_packet_results_and_live_accounting_matches_final(self):
        config = json.loads((ROOT / "scenarios/phase2/single_link.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            a = run(config, Path(temp) / "a")
            seen = []
            b = run(
                config, Path(temp) / "b", observer=lambda o: seen.append(deepcopy(o))
            )
            self.assertEqual(a, b)
            self.assertEqual(seen[0]["time_s"], 0)
            plan = json.loads((Path(temp) / "b/prepared.json").read_text())
            metrics = Metrics(plan["flows"])
            import csv

            with (Path(temp) / "b/events.tsv").open() as file:
                for row in csv.DictReader(file, delimiter="\t"):
                    metrics.event(row)
            result = metrics.at(config["duration_s"])
            self.assertEqual(result["delivered"], b["flows"][0]["delivered"])
            self.assertEqual(
                result["delivered_bytes"], b["flows"][0]["delivered_bytes"]
            )


@unittest.skipUnless(
    importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx"),
    "Install dashboard test dependencies",
)
class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from dashboard import server

        self.temp = tempfile.TemporaryDirectory()
        self.server = server
        self.patches = [
            patch.object(server, "STORE", Path(self.temp.name)),
            patch.object(server, "DB", Path(self.temp.name) / "index.sqlite3"),
            patch.object(server.supervisor, "start"),
            patch.object(server.supervisor, "shutdown"),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(server.app)
        self.client.__enter__()
        self.config = json.loads((ROOT / "scenarios/phase5/normal.json").read_text())

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_queue_cancel_persistence_and_unknown_policy(self):
        response = self.client.post(
            "/api/v1/runs",
            json=dict(scenario=self.config, name="API contract", policy="propagation"),
        )
        self.assertEqual(response.status_code, 202)
        run_id = response.json()["id"]
        self.assertEqual(self.client.get("/api/v1/runs").json()[0]["id"], run_id)
        self.assertEqual(
            self.client.post(
                f"/api/v1/runs/{run_id}/commands", json={"command": "cancel"}
            ).json()["status"],
            "cancelled",
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/runs/{run_id}/commands", json={"command": "resume"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/runs", json=dict(scenario=self.config, policy="ppo")
            ).status_code,
            422,
        )

    def test_immutable_scenario_revision_and_path_escape(self):
        a = self.client.post(
            "/api/v1/scenarios", json=dict(scenario=self.config, name="A")
        ).json()
        b = self.client.post(
            "/api/v1/scenarios", json=dict(scenario=self.config, name="B")
        ).json()
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(
            self.client.post(
                "/api/v1/imports", json={"path": "../../README.md"}
            ).status_code,
            422,
        )
        self.assertFalse(
            self.client.get("/api/v1/capabilities").json()["training_available"]
        )

    def test_replay_windows_and_malformed_import(self):
        bundle = json.loads((ROOT / "web/public/data/demo.json").read_text())
        bad = deepcopy(bundle)
        bad["frames"] = []
        self.assertEqual(
            self.client.post("/api/v1/imports", json={"bundle": bad}).status_code, 422
        )
        # 501 legitimate viewer samples make the overview bounded and seek contiguous.
        source = bundle["frames"]
        bundle["frames"] = [
            {**deepcopy(source[min(len(source) - 1, int(i / 10))]), "time_s": i / 100}
            for i in range(501)
        ]
        response = self.client.post("/api/v1/imports", json={"bundle": bundle})
        self.assertEqual(response.status_code, 201)
        run_id = response.json()["id"]
        overview = self.client.get(f"/api/v1/runs/{run_id}/replay").json()
        self.assertTrue(overview["sampled"])
        self.assertEqual(len(overview["frames"]), 160)
        window = self.client.get(f"/api/v1/runs/{run_id}/replay?center_s=2.5").json()
        self.assertFalse(window["sampled"])
        self.assertEqual(len(window["frames"]), 160)
        times = [f["time_s"] for f in window["frames"]]
        self.assertLessEqual(min(times), 2.5)
        self.assertGreaterEqual(max(times), 2.5)
        self.assertTrue(all(abs(b - a - 0.01) < 1e-9 for a, b in zip(times, times[1:])))
