"""Owned worker: browser clients never drive the packet clock."""

import csv
import json
import hashlib
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
    last_frame = None
    last_frame_time = None
    frame_offsets = []
    events = []
    last_links = None
    plan = geometry = metrics = source = None
    seq = 0
    atomic_json(
        directory / "ui-state.json", dict(status="preparing", time_s=0, sequence=seq)
    )

    def observe(obs):
        nonlocal plan, geometry, metrics, source, seq, last_links, last_frame, last_frame_time
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
        if last_frame is None or now - last_frame_time >= 0.099999:
            encoded = (json.dumps(frame, separators=(",", ":")) + "\n").encode()
            with (directory / "frames.jsonl").open("ab") as file:
                frame_offsets.append([now, file.tell()])
                file.write(encoded)
            last_frame, last_frame_time = frame, now
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
                **last_frame,
                "time_s": config["duration_s"],
                "positions": geometry.positions(config["duration_s"]),
                "metrics": metrics.at(config["duration_s"]),
            }
            encoded = (json.dumps(final, separators=(",", ":")) + "\n").encode()
            with (directory / "frames.jsonl").open("ab") as file:
                frame_offsets.append([final["time_s"], file.tell()])
                file.write(encoded)
            last_frame = final
        bundle = dict(
            schema_version=1,
            id=job["id"],
            name=job["name"],
            policy=job["policy"],
            status="completed",
            scenario=config,
            nodes=metadata(config, plan["nodes"]),
            duration_s=config["duration_s"],
            frames=[],
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
        # Keep frame payloads independently addressable. The API can seek into
        # large runs without deserializing the entire replay bundle.
        atomic_json(directory / "replay-index.json", {"schema_version": 1, "file": "frames.jsonl", "frames": frame_offsets})
        bundle["frames"] = []
        bundle["frame_count"] = len(frame_offsets)
        bundle["provenance"] = {
            "scenario_hash": job.get("scenario_hash"),
            "policy": job.get("policy"),
            "checkpoint": job.get("checkpoint"),
            "encoder_version": job.get("encoder_version"),
            "calibration": job.get("calibration"),
            "source_version": job.get("source_version"),
            "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest()
            if (directory / "manifest.json").exists() else None,
        }
        atomic_json(directory / "replay.json", bundle)
        atomic_json(
            directory / "ui-state.json",
            dict(
                status="completed",
                time_s=config["duration_s"],
                sequence=seq + 1,
                frame=last_frame,
                wall_seconds=time.time() - started,
            ),
        )
    except Exception as exc:
        atomic_json(
            directory / "ui-state.json",
            dict(
                status="failed",
                error=str(exc),
                time_s=last_frame["time_s"] if last_frame else 0,
                sequence=seq + 1,
            ),
        )
        raise


if __name__ == "__main__":
    main(sys.argv[1])
