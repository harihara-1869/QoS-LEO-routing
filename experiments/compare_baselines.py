"""Matched Phase 3 smoke comparisons; final research evaluation belongs to Phase 7."""

import argparse
import hashlib
import json
from pathlib import Path

from experiments.run import run
from packet_backend.workloads import CASES, workload


def compare(case, output, seed=7):
    config = workload(case, seed)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").unlink(missing_ok=True)
    encoded = json.dumps(config, sort_keys=True, indent=2) + "\n"
    (output / "scenario.json").write_text(encoded)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    policies = {}
    for policy in ("propagation", "congestion"):
        result = run(config, output / policy, policy=policy)
        policies[policy] = {
            "scenario_sha256": digest,
            "qos": result["qos"],
            "route_changes": sum(f["route_changes"] for f in result["flows"]),
            "result_sha256": json.loads(
                (output / policy / "manifest.json").read_text()
            )["result_sha256"],
        }
    summary = {
        "case": case,
        "seed": seed,
        "scenario_sha256": digest,
        "comparison": "Same traffic, topology, service targets, scheduler and control times; only routing changes.",
        "policies": policies,
    }
    (output / "comparison.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="runs/phase3")
    args = parser.parse_args()
    for case in CASES if args.case == "all" else (args.case,):
        result = compare(case, Path(args.output) / case, args.seed)
        print(
            case,
            {
                p: {c: round(m["goodput_bps"]) for c, m in r["qos"]["classes"].items()}
                for p, r in result["policies"].items()
            },
        )
