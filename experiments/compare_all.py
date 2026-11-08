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

    # Locate and validate NS-CRPO checkpoint
    if checkpoint_path is None:
        for candidate in (
            Path("results/learning_nscrpo/best_model.pt"),
            Path("runs/learning_nscrpo/best_model.pt"),
            Path("/kaggle/working/results/learning_nscrpo/best_model.pt"),
            Path("/kaggle/working/runs/learning_nscrpo/best_model.pt"),
        ):
            if candidate.exists():
                checkpoint_path = candidate
                break

    if checkpoint_path is not None:
        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Specified NS-CRPO checkpoint not found: {checkpoint_path}")
        policies_to_run.append(f"ns_crpo:{checkpoint_path}")

    results_table = []
    audit_table = []
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

        # Per-class metrics extraction helper
        def extract_class_metrics(c_name: str):
            c_stats = classes.get(c_name, {})
            gen = c_stats.get("udp_generated", c_stats.get("generated", 0))
            deliv = c_stats.get("udp_delivered", c_stats.get("delivered", 0))
            drop = c_stats.get("udp_dropped", c_stats.get("dropped", 0))
            in_fl = c_stats.get("udp_in_flight", 0)
            undeliv = c_stats.get("udp_undelivered", drop + in_fl)
            on_time = c_stats.get("on_time_count", c_stats.get("deadline", {}).get("on_time", 0))
            late = c_stats.get("late_count", c_stats.get("deadline", {}).get("late", 0))

            deadline_success_pct = (on_time / gen * 100.0) if gen > 0 else 0.0
            on_time_deliv_pct = (on_time / deliv * 100.0) if deliv > 0 else 0.0
            miss_rate_pct = ((gen - on_time) / gen * 100.0) if gen > 0 else 0.0

            deadline_s = c_stats.get("configured_deadline_s")
            mean_s = c_stats.get("delay_mean_s")
            med_s = c_stats.get("delay_median_s")
            p95_s = c_stats.get("delay_p95_s")
            p99_s = c_stats.get("delay_p99_s")
            sample_count = c_stats.get("sample_count", deliv)

            return {
                "generated": gen,
                "delivered": deliv,
                "dropped": drop,
                "in_flight": in_fl,
                "undelivered": undeliv,
                "on_time": on_time,
                "late": late,
                "deadline_success_rate_pct": deadline_success_pct,
                "on_time_among_delivered_pct": on_time_deliv_pct,
                "deadline_miss_rate_pct": miss_rate_pct,
                "goodput_bps": c_stats.get("goodput_bps", 0.0),
                "configured_deadline_s": deadline_s,
                "deadline_ms": (deadline_s * 1000.0) if deadline_s is not None else None,
                "mean_latency_ms": (mean_s * 1000.0) if mean_s is not None else None,
                "median_latency_ms": (med_s * 1000.0) if med_s is not None else None,
                "p95_latency_ms": (p95_s * 1000.0) if p95_s is not None else None,
                "p99_latency_ms": (p99_s * 1000.0) if p99_s is not None else None,
                "sample_count": sample_count,
            }

        ctrl_m = extract_class_metrics("CONTROL")
        rt_m = extract_class_metrics("REALTIME")
        bulk_m = extract_class_metrics("BULK")

        delivered = sum(f.get("delivered", 0) for f in flows)
        dropped = sum(f.get("dropped", 0) for f in flows)
        churn = sum(f.get("route_changes", 0) for f in flows)
        bulk_goodput_kbps = bulk_m["goodput_bps"] / 1000.0

        # Primary benchmark summary row
        row = {
            "Policy": p_name,
            "Delivered": delivered,
            "Dropped": dropped,
            "Control On-Time (%)": f"{ctrl_m['deadline_success_rate_pct']:.1f}%",
            "Control Deliv On-Time (%)": f"{ctrl_m['on_time_among_delivered_pct']:.1f}%",
            "Realtime On-Time (%)": f"{rt_m['deadline_success_rate_pct']:.1f}%",
            "Realtime Deliv On-Time (%)": f"{rt_m['on_time_among_delivered_pct']:.1f}%",
            "Bulk Goodput (kbps)": f"{bulk_goodput_kbps:.1f}",
            "Route Churn": churn,
        }
        results_table.append(row)

        for c_label, m in [("CONTROL", ctrl_m), ("REALTIME", rt_m), ("BULK", bulk_m)]:
            audit_table.append({
                "Policy": p_name,
                "Class": c_label,
                "Gen": m["generated"],
                "Deliv": m["delivered"],
                "OnTime": m["on_time"],
                "Late": m["late"],
                "Undeliv": m["undelivered"],
                "Deadline(ms)": f"{m['deadline_ms']:.1f}" if m['deadline_ms'] is not None else "—",
                "Mean(ms)": f"{m['mean_latency_ms']:.1f}" if m['mean_latency_ms'] is not None else "—",
                "Med(ms)": f"{m['median_latency_ms']:.1f}" if m['median_latency_ms'] is not None else "—",
                "P95(ms)": f"{m['p95_latency_ms']:.1f}" if m['p95_latency_ms'] is not None else "—",
                "P99(ms)": f"{m['p99_latency_ms']:.1f}" if m['p99_latency_ms'] is not None else "—",
                "E2E Succ(%)": f"{m['deadline_success_rate_pct']:.1f}%" if m['deadline_ms'] is not None else "—",
                "Deliv OnTime(%)": f"{m['on_time_among_delivered_pct']:.1f}%" if m['deadline_ms'] is not None else "—",
            })

        comparison_records[p_name] = {
            "summary": row,
            "control": ctrl_m,
            "realtime": rt_m,
            "bulk": bulk_m,
            "aggregate": {
                "delivered": delivered,
                "dropped": dropped,
                "route_churn": churn,
            },
        }

    # Print publication-ready Markdown table 1: Overall Benchmark
    print("\n" + "#" * 110)
    print("### PUBLICATION RESEARCH BENCHMARK TABLE")
    print("#" * 110)
    headers = [
        "Policy", "Delivered", "Dropped",
        "Ctrl On-Time (Gen %)", "Ctrl On-Time (Deliv %)",
        "RT On-Time (Gen %)", "RT On-Time (Deliv %)",
        "Bulk Goodput (kbps)", "Route Churn"
    ]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    print(header_line)
    print(sep_line)
    for r in results_table:
        print(f"| {r['Policy']:<15} | {r['Delivered']:<9} | {r['Dropped']:<7} | "
              f"{r['Control On-Time (%)']:<20} | {r['Control Deliv On-Time (%)']:<22} | "
              f"{r['Realtime On-Time (%)']:<18} | {r['Realtime Deliv On-Time (%)']:<20} | "
              f"{r['Bulk Goodput (kbps)']:<19} | {r['Route Churn']:<11} |")

    # Print detailed Table 2: Detailed QoS Latency & Deadline Audit Table
    print("\n" + "#" * 110)
    print("### DETAILED QOS LATENCY & DEADLINE AUDIT TABLE")
    print("#" * 110)
    audit_headers = [
        "Policy", "Class", "Gen", "Deliv", "OnTime", "Late", "Undeliv",
        "Deadline(ms)", "Mean(ms)", "Med(ms)", "P95(ms)", "P99(ms)", "E2E Succ(%)", "Deliv OnTime(%)"
    ]
    audit_header_line = "| " + " | ".join(audit_headers) + " |"
    audit_sep_line = "| " + " | ".join(["---"] * len(audit_headers)) + " |"
    print(audit_header_line)
    print(audit_sep_line)
    for a in audit_table:
        print(f"| {a['Policy']:<15} | {a['Class']:<8} | {a['Gen']:<5} | {a['Deliv']:<5} | "
              f"{a['OnTime']:<6} | {a['Late']:<4} | {a['Undeliv']:<7} | "
              f"{a['Deadline(ms)']:<12} | {a['Mean(ms)']:<8} | {a['Med(ms)']:<7} | "
              f"{a['P95(ms)']:<7} | {a['P99(ms)']:<7} | {a['E2E Succ(%)']:<11} | {a['Deliv OnTime(%)']:<16} |")

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

