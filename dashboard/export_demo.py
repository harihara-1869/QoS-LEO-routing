"""Export actual recorded output as a self-contained offline demonstration."""

import argparse

from dashboard.data import atomic_json, build_replay

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="runs/fidelity/evaluation/normal_predictive")
    p.add_argument("--output", default="web/public/data/demo.json")
    p.add_argument("--id", default="demo-handover")
    p.add_argument("--name", default="Aurora · Predictive handover")
    a = p.parse_args()
    r = build_replay(a.run, a.id, a.name)
    r["bundled"] = True
    atomic_json(a.output, r)
    print("Exported", len(r["frames"]), "frames from", a.run)
