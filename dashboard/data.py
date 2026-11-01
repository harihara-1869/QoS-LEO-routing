"""Authoritative simulation → bounded browser data adapters."""

import hashlib
import json
import math
import tempfile
from pathlib import Path

import numpy as np
from skyfield.framelib import itrs

from constellation.topology import LogicalConfig
from packet_backend.qos import CLASSES
from packet_backend.results import percentile, route_path
from packet_backend.scenario import prepare
from constellation.omm import get_satellite_data
from constellation.snapshots import TopologySnapshots

POLICIES = [
    dict(
        id=i,
        label=label,
        kind="heuristic",
        available=True,
        checkpoint_required=False,
        observation_version=1,
        action_version=1,
    )
    for i, label in [
        ("propagation", "Propagation Dijkstra"),
        ("congestion", "Congestion-aware Dijkstra"),
        ("qos_current", "Current-state QoS"),
        ("lifetime", "Link lifetime"),
        ("queue_forecast", "Queue forecast"),
        ("predictive", "Predictive QoS"),
    ]
]


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, allow_nan=False, separators=(",", ":")))
    tmp.replace(path)


def check_limits(c):
    if not isinstance(c, dict):
        raise ValueError("A scenario object is required")
    d = c.get("duration_s", 0)
    if not isinstance(d, (int, float)) or not math.isfinite(d) or not 0 < d <= 600:
        raise ValueError("Duration must be between 0 and 600 seconds")
    a = c.get("constellation", {})
    n = a.get("n_planes", 0) * a.get("sats_per_plane", 0)
    if not isinstance(n, int) or not 1 <= n <= 1000:
        raise ValueError("Use between 1 and 1,000 satellites")
    for k in ("step_s", "control_interval_s"):
        s = c.get(k, 1)
        if (
            not isinstance(s, (int, float))
            or not math.isfinite(s)
            or s <= 0
            or d / s > 4000
        ):
            raise ValueError("Use at most 4,000 physical/control updates")
    for f in c.get("flows", []):
        fid = f.get("flow_id", "?")
        end = f.get("end_time")
        start = f.get("start_time", 0)
        if (
            isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not math.isfinite(end)
            or end <= 0
        ):
            raise ValueError(f"Flow {fid} needs a positive end time")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or not math.isfinite(start)
            or start < 0
        ):
            raise ValueError(f"Flow {fid} needs a nonnegative start time")
        if not start < min(end, d):
            raise ValueError(
                f"Flow {fid} must start before its end time and the mission duration"
            )
    packets = sum(
        max(0, min(f.get("end_time", d), d) - f.get("start_time", 0))
        * f.get("data_rate_bps", 0)
        / max(1, f.get("packet_size_bytes", 1000) * 8)
        for f in c.get("flows", [])
        if f.get("protocol", "udp") == "udp"
    )
    if packets > 100000:
        raise ValueError(
            "Reduce duration or demand: local runs support 100,000 offered UDP packets"
        )
    return dict(
        satellites=n,
        estimated_packets=round(packets),
        control_updates=math.ceil(d / c.get("control_interval_s", 1)),
    )


def validate_bundle(bundle):
    """Validate portable viewer data before it becomes durable library content."""
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        raise ValueError("Unsupported replay schema")
    if bundle.get("frame") != "ECEF" or bundle.get("units") != "km":
        raise ValueError("Replay geometry must declare ECEF coordinates in km")
    for key in ("name", "status", "source"):
        if not isinstance(bundle.get(key), str):
            raise ValueError(f"Replay needs {key}")
    scenario = bundle.get("scenario", {})
    if not isinstance(scenario, dict) or not isinstance(scenario.get("flows"), list):
        raise ValueError("Replay needs its source scenario and flows")
    nodes = bundle.get("nodes")
    frames = bundle.get("frames")
    duration = bundle.get("duration_s")
    if not isinstance(nodes, list) or not nodes or len(nodes) > 1100:
        raise ValueError("Replay needs at most 1,100 nodes")
    if (
        not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("Replay duration must be positive and finite")
    if not isinstance(frames, list) or not 1 <= len(frames) <= 10000:
        raise ValueError("Replay needs between 1 and 10,000 frames")
    for i, n in enumerate(nodes):
        if n.get("id") != i or not isinstance(n.get("name"), str):
            raise ValueError("Replay node IDs must be contiguous and named")
    last = -1
    for f in frames:
        t = f.get("time_s")
        if (
            not isinstance(t, (int, float))
            or not math.isfinite(t)
            or t < last
            or not 0 <= t <= duration + 1e-6
        ):
            raise ValueError("Replay frames must be ordered within the episode")
        last = t
        if any(
            not isinstance(f.get(key), list)
            for key in ("positions", "links", "routes", "queues")
        ):
            raise ValueError("Replay frames need position/link/route/queue arrays")
        if f["positions"] and (
            len(f["positions"]) != len(nodes)
            or any(
                len(p) != 3
                or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v) for v in p
                )
                for p in f["positions"]
            )
        ):
            raise ValueError("Replay positions need one finite XYZ point per node")
        m = f.get("metrics")
        if m is not None and (
            not isinstance(m, dict)
            or any(
                key not in m
                for key in ("generated", "delivered", "dropped", "in_flight", "classes")
            )
            or any(k not in m.get("classes", {}) for k in CLASSES)
        ):
            raise ValueError("Replay metric records are incomplete")
    return bundle


class Geometry:
    def __init__(self, c, csv):
        self.config = c
        self.sim = TopologySnapshots(
            get_satellite_data(csv_file=csv),
            c["epoch"],
            LogicalConfig(**c["links"]),
            c["ground_stations"],
            c.get("orbital_start_s", 0),
        )
        self.cache = {}

    def positions(self, seconds):
        k = round(seconds, 6)
        if k in self.cache:
            return self.cache[k]
        t = self.sim.get_sim_time(seconds)
        rotation = itrs.rotation_at(t)
        points = [rotation @ n.sat.at(t).position.km for n in self.sim.topology.nodes]
        points += [
            rotation @ self.sim.topology.get_gs_position(name, t)
            for name, *_ in self.config["ground_stations"]
        ]
        result = [[round(float(v), 4) for v in point] for point in points]
        self.cache[k] = result
        if len(self.cache) > 128:
            self.cache.pop(next(iter(self.cache)))
        return result


def metadata(c, names):
    ground = {g[0]: g for g in c.get("ground_stations", [])}
    return [
        dict(
            id=i,
            name=n,
            kind="ground"
            if n in ground
            else "network"
            if "topology" in c
            else "satellite",
            coordinates=ground[n][1:] if n in ground else None,
        )
        for i, n in enumerate(names)
    ]


def packet_metrics(packets, flows, t, tcp_bytes=0):
    result = dict(
        generated=0, delivered=0, dropped=0, in_flight=0, delivered_bytes=0, classes={}
    )
    all_delays = []
    for name in CLASSES:
        subset = [
            p
            for p in packets
            if flows.get(p["flow_id"], {}).get("flow_type", "BULK") == name
        ]
        c = dict(
            generated=len(subset),
            delivered=0,
            dropped=0,
            in_flight=0,
            delivered_bytes=0,
        )
        on_time = resolved = 0
        delays = []
        for p in subset:
            status = p["status"] if p["ended_s"] <= t + 1e-8 else "in_flight"
            c[
                "delivered"
                if status == "delivered"
                else "dropped"
                if status == "dropped"
                else "in_flight"
            ] += 1
            deadline = flows.get(p["flow_id"], {}).get("deadline_s")
            if status == "delivered":
                delay = p["ended_s"] - p["created_s"]
                delays.append(delay)
                c["delivered_bytes"] += p["size_bytes"]
                if deadline is not None:
                    resolved += 1
                    on_time += delay <= deadline + 1e-9
            elif deadline is not None and (
                status == "dropped" or p["created_s"] + deadline <= t
            ):
                resolved += 1
        c.update(
            delay_p95_s=percentile(delays, 0.95),
            deadline_success=on_time / resolved if resolved else None,
            goodput_bps=c["delivered_bytes"] * 8 / t if t > 0 else 0,
        )
        all_delays.extend(delays)
        result["classes"][name] = c
        for key in (
            "generated",
            "delivered",
            "dropped",
            "in_flight",
            "delivered_bytes",
        ):
            result[key] += c[key]
    result["classes"]["BULK"]["delivered_bytes"] += tcp_bytes
    result["classes"]["BULK"]["goodput_bps"] = (
        result["classes"]["BULK"]["delivered_bytes"] * 8 / t if t else 0
    )
    result["delivered_bytes"] += tcp_bytes
    result.update(
        goodput_bps=result["delivered_bytes"] * 8 / t if t else 0,
        delay_mean_s=sum(all_delays) / len(all_delays) if all_delays else None,
        delay_p95_s=percentile(all_delays, 0.95),
        delivery_ratio=result["delivered"] / result["generated"]
        if result["generated"]
        else None,
    )
    return result


class Metrics:
    def __init__(self, flows):
        self.flows = {f["id"]: f for f in flows}
        self.packets = {}
        self.tcp_bytes = 0

    def event(self, e):
        kind = e["kind"]
        fid = int(e["item"])
        pid = int(e["a"])
        t = float(e["time_s"])
        if kind == "udp_created":
            self.packets[pid] = dict(
                flow_id=fid,
                size_bytes=int(float(e["value"])),
                created_s=t,
                status="in_flight",
                ended_s=t,
            )
        elif kind in ("udp_delivered", "udp_dropped") and pid in self.packets:
            self.packets[pid].update(
                status="delivered" if kind == "udp_delivered" else "dropped", ended_s=t
            )
        elif kind == "tcp_receive":
            self.tcp_bytes += float(e["value"])

    def at(self, t):
        return packet_metrics(
            [p for p in self.packets.values() if p["created_s"] <= t + 1e-8],
            self.flows,
            t,
            self.tcp_bytes,
        )


def flow_routes(plan, obs):
    result = []
    for f in plan["flows"]:
        rows = (
            [r[1:] for r in obs.get("class_routes", []) if r[0] == f["class_id"]]
            if "class_routes" in obs
            else obs["routes"]
        )
        result.append(
            dict(
                id=f["id"],
                flow_type=f["flow_type"],
                src=f["src"],
                dst=f["dst"],
                path=route_path(rows, f["src"], f["dst"]),
            )
        )
    return result


def preview(c):
    check_limits(c)
    with tempfile.TemporaryDirectory(prefix="leo-preview-") as temp:
        p = Path(temp)
        plan = prepare(c, p, class_routing=True)
        g = Geometry(c, p / "constellation.csv")
        frames = []
        index = 0
        for t in np.linspace(0, c["duration_s"] - 1e-6, 25):
            while (
                index + 1 < len(plan["snapshots"])
                and plan["snapshots"][index + 1]["time_s"] <= t
            ):
                index += 1
            s = plan["snapshots"][index]
            links = [
                {**plan["links"][e["id"]], "delay_s": e["delay_s"]} for e in s["links"]
            ]
            frames.append(
                dict(
                    time_s=round(float(t), 6),
                    positions=g.positions(float(t)),
                    links=links,
                    metrics=None,
                    routes=[],
                    queues=[],
                )
            )
        return dict(
            schema_version=1,
            id="preview",
            name="Constellation preview",
            status="preview",
            scenario=c,
            nodes=metadata(c, plan["nodes"]),
            duration_s=c["duration_s"],
            frames=frames,
            events=[],
            policy=None,
            frame="ECEF",
            units="km",
            capabilities=dict(metrics=False, geometry=True, forecast=False),
            source="Authoritative orbital model · preview only",
        )


def build_replay(directory, run_id=None, name=None):
    p = Path(directory)
    r = read_json(p / "results.json")
    plan = read_json(p / "prepared.json")
    if not r or not plan:
        raise ValueError(
            "Supported replay needs results.json and prepared.json from a packet run"
        )
    for f in plan["flows"]:
        f.setdefault("class_id", 2)
        f.setdefault("flow_type", "BULK")
        f.setdefault("deadline_s", None)
    c = plan["source_scenario"]
    g = (
        Geometry(c, p / "constellation.csv")
        if (p / "constellation.csv").exists()
        else None
    )
    rows = read_json(p / "control.json", r.get("route_snapshots", []))
    frames = []
    events = []
    tcp = []
    if (p / "events.tsv").exists() and any(
        f["protocol"] == "tcp" for f in plan["flows"]
    ):
        import csv

        with (p / "events.tsv").open() as file:
            tcp = [
                (float(e["time_s"]), float(e["value"]))
                for e in csv.DictReader(file, delimiter="\t")
                if e["kind"] == "tcp_receive"
            ]
    flows = {f["id"]: f for f in plan["flows"]}
    packets = r.get("udp_packets", [])
    for t in [
        *np.linspace(0, max(0, plan["duration_s"] - 1e-7), 51),
        plan["duration_s"],
    ]:
        s = max(
            (s for s in plan["snapshots"] if s["time_s"] <= t + 1e-8),
            key=lambda s: s["time_s"],
        )
        obs = max(
            (s for s in rows if s["time_s"] <= t + 1e-8),
            key=lambda s: s["time_s"],
            default={"routes": []},
        )
        frames.append(
            dict(
                time_s=round(float(t), 6),
                positions=g.positions(float(t)) if g else [],
                links=[
                    {**plan["links"][e["id"]], "delay_s": e["delay_s"]}
                    for e in s["links"]
                ],
                metrics=packet_metrics(
                    [p for p in packets if p["created_s"] <= t + 1e-8],
                    flows,
                    t,
                    sum(value for ts, value in tcp if ts <= t),
                ),
                routes=flow_routes(plan, obs),
                queues=[
                    {
                        **{
                            k: q[k]
                            for k in ("link_id", "direction", "packets", "bytes")
                            if k in q
                        },
                        **(
                            {
                                "bytes": sum(
                                    v.get("bytes", 0) for v in q["classes"].values()
                                )
                            }
                            if "bytes" not in q and q.get("classes")
                            else {}
                        ),
                    }
                    for q in obs.get("queues", [])
                ],
                forecast=obs.get("prediction", {}).get("decisions", []),
            )
        )
    previous = set()
    for s in plan["snapshots"]:
        current = {e["id"] for e in s["links"]}
        if previous and current != previous:
            events.append(
                dict(
                    time_s=s["time_s"],
                    kind="handover",
                    title="Topology transition",
                    detail=f"{len(previous - current)} removed · {len(current - previous)} established",
                )
            )
        previous = current
    digest = hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
    manifest = read_json(p / "manifest.json", {})
    return dict(
        schema_version=1,
        id=run_id or digest[:16],
        name=name or p.name.replace("_", " ").title(),
        status="completed",
        policy={
            "shortest_routes": "propagation",
            "congestion_routes": "congestion",
        }.get(
            r.get("routing_policy", "unknown").rsplit(".", 1)[-1],
            r.get("routing_policy", "unknown").rsplit(".", 1)[-1],
        ),
        scenario=c,
        nodes=metadata(c, plan["nodes"]),
        duration_s=plan["duration_s"],
        frames=frames,
        events=events,
        frame="ECEF",
        units="km",
        scenario_hash=digest,
        source_hashes=manifest.get("source_sha256", {}),
        result_hash=manifest.get("result_sha256"),
        capabilities=dict(
            metrics=True, geometry=g is not None, forecast=bool(r.get("prediction"))
        ),
        summary=r.get("qos", {}),
        source="Recorded ns-3 packet simulation · original topology and routes",
    )
