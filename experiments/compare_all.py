"""Comprehensive evaluation comparing all 6 heuristics against simpler RL and NS-CRPO."""
import argparse
import json
from pathlib import Path
from experiments.run import run


HEURISTIC_POLICIES = [
    "propagation",
    "congestion",
    "qos_current",
    "lifetime",
    "queue_forecast",
    "predictive",
]


def evaluate_suite(scenario_path: Path, output_dir: Path, checkpoint_path: Path | None = None):
    scenario_path = Path(scenario_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_cfg = json.loads(scenario_path.read_text())
    policies_to_run = list(HEURISTIC_POLICIES)
    policies_to_run.append("simpler_rl")

    if checkpoint_path and Path(checkpoint_path).exists():
        policies_to_run.append(f"learned:{checkpoint_path}")

    results_table = []
    comparison_records = {}

    print("\n" + "=" * 90)
    print(f"RUNNING MATCHED EVALUATION ON: {scenario_path.name}")
    print("=" * 90)

    for p in policies_to_run:
        p_name = p.split(":")[0]
        run_out = output_dir / p_name
        print(f"--> Executing policy: {p} ...", flush=True)

        res = run(scenario_cfg, run_out, policy=p)

        qos = res.get("qos", {})
        classes = qos.get("classes", {})
        flows = res.get("flows", [])

        # Metrics extraction
        ctrl_stats = classes.get("CONTROL", {})
        rt_stats = classes.get("REALTIME", {})
        bulk_stats = classes.get("BULK", {})

        ctrl_success_pct = (ctrl_stats.get("deadline_met", 0) / max(1, ctrl_stats.get("delivered", 0))) * 100.0
        rt_success_pct = (rt_stats.get("deadline_met", 0) / max(1, rt_stats.get("delivered", 0))) * 100.0
        bulk_goodput_kbps = bulk_stats.get("goodput_bps", 0.0) / 1000.0

        delivered = sum(f.get("delivered", 0) for f in flows)
        dropped = sum(f.get("dropped", 0) for f in flows)
        churn = sum(f.get("route_changes", 0) for f in flows)

        row = {
            "Policy": p_name,
            "Delivered": delivered,
            "Dropped": dropped,
            "Control On-Time (%)": f"{ctrl_success_pct:.1f}%",
            "Realtime On-Time (%)": f"{rt_success_pct:.1f}%",
            "Bulk Goodput (kbps)": f"{bulk_goodput_kbps:.1f}",
            "Route Churn": churn,
        }
        results_table.append(row)
        comparison_records[p_name] = row

    # Print publication-ready Markdown table
    print("\n" + "#" * 90)
    print("### PUBLICATION RESEARCH BENCHMARK TABLE")
    print("#" * 90)
    headers = ["Policy", "Delivered", "Dropped", "Control On-Time (%)", "Realtime On-Time (%)", "Bulk Goodput (kbps)", "Route Churn"]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    print(header_line)
    print(sep_line)
    for r in results_table:
        print(f"| {r['Policy']:<18} | {r['Delivered']:<9} | {r['Dropped']:<7} | {r['Control On-Time (%)']:<19} | {r['Realtime On-Time (%)']:<20} | {r['Bulk Goodput (kbps)']:<19} | {r['Route Churn']:<11} |")

    # Save summary json
    (output_dir / "comparison_summary.json").write_text(json.dumps(comparison_records, indent=2))
    print(f"\n[Evaluation] Saved complete comparison to {output_dir / 'comparison_summary.json'}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate heuristics vs RL")
    parser.add_argument("--scenario", type=Path, default=Path("scenarios/phase5/normal.json"))
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("runs/full_comparison"))
    args = parser.parse_args()
    evaluate_suite(args.scenario, args.output, args.checkpoint)

