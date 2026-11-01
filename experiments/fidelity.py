"""Reproduce terminal/handover evidence and expose timing-scale sensitivity."""

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path

from experiments.run import run
from packet_backend.orbital_workloads import orbital_workload


def scaled_scenario(config, factor, matched_demand=False):
    if (
        isinstance(factor, bool)
        or not isinstance(factor, (int, float))
        or not math.isfinite(factor)
        or factor <= 0
    ):
        raise ValueError("Capacity scale must be positive and finite")
    result = deepcopy(config)
    for name in ("isl_capacity_bps", "ground_capacity_bps"):
        result["links"][name] = max(1, round(result["links"][name] * factor))
    if matched_demand:
        for flow in result["flows"]:
            flow["data_rate_bps"] = round(flow["data_rate_bps"] * factor)
    return result


def summarize(directory, result):
    plan = json.loads((directory / "prepared.json").read_text())
    control = json.loads((directory / "control.json").read_text())
    previous = None
    changes = []
    for snap in plan["snapshots"]:
        active = {e["id"] for e in snap["links"]}
        if previous is not None and active != previous:
            changes.append(
                {
                    "time_s": snap["time_s"],
                    "added": len(active - previous),
                    "removed": len(previous - active),
                }
            )
        previous = active
    stations = {gs[0] for gs in result["scenario"]["ground_stations"]}
    manifest = json.loads((directory / "manifest.json").read_text())
    return {
        "result_sha256": manifest["result_sha256"],
        "source_sha256": manifest["source_sha256"],
        "scenario_sha256": hashlib.sha256(
            json.dumps(result["scenario"], sort_keys=True).encode()
        ).hexdigest(),
        "generated": sum(f["generated"] for f in result["flows"]),
        "delivered": sum(f["delivered"] for f in result["flows"]),
        "dropped": sum(f["dropped"] for f in result["flows"]),
        "in_flight": sum(f["in_flight"] for f in result["flows"]),
        "classes": result["qos"]["classes"],
        "prediction": {
            k: v for k, v in result["prediction"].items() if k != "fallbacks"
        },
        "topology_changes": changes,
        "active_flow_ticks": {
            str(f["id"]): [
                o["time_s"]
                for o in control
                if any(a["id"] == f["id"] for a in o.get("active_flows", []))
            ]
            for f in plan["flows"]
        },
        "gateway_transit_deliveries": sum(
            any(n in stations for n in p["path"][1:-1])
            for p in result["udp_packets"]
            if p["status"] == "delivered"
        ),
        "ground_capacity_bps": result["scenario"]["links"]["ground_capacity_bps"],
        "bulk_wire_serialization_s": 1230
        * 8
        / result["scenario"]["links"]["ground_capacity_bps"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/fidelity/evaluation"))
    parser.add_argument(
        "--evidence", type=Path, default=Path("runs/fidelity/evidence.json")
    )
    parser.add_argument(
        "--quick", action="store_true", help="Normal predictive episode only"
    )
    args = parser.parse_args()
    args.evidence.unlink(missing_ok=True)
    base = orbital_workload("normal")
    experiments = [("normal_predictive", base, "predictive")]
    if not args.quick:
        experiments += [
            ("normal_propagation", base, "propagation"),
            ("burst_predictive", orbital_workload("burst"), "predictive"),
            ("overload_predictive", orbital_workload("overload"), "predictive"),
            ("capacity_x2_fixed_demand", scaled_scenario(base, 2), "propagation"),
            (
                "capacity_x2_matched_demand",
                scaled_scenario(base, 2, True),
                "propagation",
            ),
        ]
    evidence = {}
    for name, config, policy in experiments:
        directory = args.output / name
        result = run(config, directory, policy=policy)
        evidence[name] = summarize(directory, result)
        print(
            name,
            {
                k: evidence[name][k]
                for k in ("generated", "delivered", "dropped", "topology_changes")
            },
            flush=True,
        )
        del result
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
