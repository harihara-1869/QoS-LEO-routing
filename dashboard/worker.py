"""Owned worker: browser clients never drive the packet clock."""

import csv
import json
import sys
import time
from pathlib import Path

from dashboard.data import (
    Geometry,
    Metrics,
    atomic_json,
    flow_routes,
    metadata,
    read_json,
)
from experiments.run import run


def main(directory):
    directory = Path(directory)
    job = read_json(directory / "job.json")
    config = job["scenario"]
    frames = []
    events = []
    last_links = None
    plan = geometry = metrics = source = None
    seq = 0
    atomic_json(
        directory / "ui-state.json", dict(status="preparing", time_s=0, sequence=seq)
    )

    def observe(obs):
        nonlocal plan, geometry, metrics, source, seq, last_links
        if plan is None:
            plan = read_json(directory / "prepared.json")
            geometry = Geometry(config, directory / "constellation.csv")
            metrics = Metrics(plan["flows"])
            source = (directory / "events.tsv").open()
            header = source.readline().strip().split("\t")
            observe.header = header
        while line := source.readline():
            row = dict(zip(observe.header, next(csv.reader([line], delimiter="\t"))))
            metrics.event(row)
        now = obs["time_s"]
        active = {e["id"] for e in obs["links"]}
        if last_links is not None and last_links != active:
            events.append(
                dict(
                    time_s=now,
                    kind="handover",
                    title="Link state changed",
                    detail=f"{len(last_links - active)} removed · {len(active - last_links)} established",
                )
            )
        last_links = active
        frame = dict(
            time_s=now,
            positions=geometry.positions(now),
            links=obs["links"],
            metrics=metrics.at(now),
            routes=flow_routes(plan, obs),
            queues=obs["queues"],
            forecast=obs.get("prediction", {}).get("decisions", []),
        )
        if not frames or now - frames[-1]["time_s"] >= 0.099999:
            frames.append(frame)
            with (directory / "frames.jsonl").open("a") as file:
                file.write(json.dumps(frame, separators=(",", ":")) + "\n")
        seq += 1

        def publish(status):
            atomic_json(
                directory / "ui-state.json",
                dict(
                    status=status,
                    time_s=now,
                    sequence=seq,
                    frame=frame,
                    nodes=metadata(config, plan["nodes"]),
                    events=events[-100:],
                    wall_seconds=time.time() - started,
                ),
            )

        command = read_json(directory / "command.json", {}).get("command")
        if command == "pause":
            publish("paused")
            while read_json(directory / "command.json", {}).get("command") == "pause":
                time.sleep(0.1)
        publish("running")

    started = time.time()
    try:
        result = run(config, directory, policy=job["policy"], observer=observe)
        if source:
            while line := source.readline():
                metrics.event(
                    dict(zip(observe.header, next(csv.reader([line], delimiter="\t"))))
                )
            source.close()
        if plan is not None:
            final = {
                **frames[-1],
                "time_s": config["duration_s"],
                "positions": geometry.positions(config["duration_s"]),
                "metrics": metrics.at(config["duration_s"]),
            }
            frames.append(final)
        bundle = dict(
            schema_version=1,
            id=job["id"],
            name=job["name"],
            policy=job["policy"],
            status="completed",
            scenario=config,
            nodes=metadata(config, plan["nodes"]),
            duration_s=config["duration_s"],
            frames=frames,
            events=events,
            frame="ECEF",
            units="km",
            scenario_hash=job["scenario_hash"],
            summary=result.get("qos"),
            source="Recorded ns-3 packet simulation",
            capabilities=dict(
                metrics=True, geometry=True, forecast="prediction" in result
            ),
        )
        manifest = read_json(directory / "manifest.json", {})
        bundle.update(
            result_hash=manifest.get("result_sha256"),
            source_hashes=manifest.get("source_sha256", {}),
        )
        atomic_json(directory / "replay.json", bundle)
        atomic_json(
            directory / "ui-state.json",
            dict(
                status="completed",
                time_s=config["duration_s"],
                sequence=seq + 1,
                frame=frames[-1],
                wall_seconds=time.time() - started,
            ),
        )
    except Exception as exc:
        atomic_json(
            directory / "ui-state.json",
            dict(
                status="failed",
                error=str(exc),
                time_s=frames[-1]["time_s"] if frames else 0,
                sequence=seq + 1,
            ),
        )
        raise


if __name__ == "__main__":
    main(sys.argv[1])
