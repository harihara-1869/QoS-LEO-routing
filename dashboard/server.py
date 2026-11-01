"""Single-machine API, durable run index and owned simulation job supervisor."""

import asyncio
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dashboard.data import (
    POLICIES,
    atomic_json,
    build_replay,
    check_limits,
    preview,
    read_json,
    validate_bundle,
)
from packet_backend.build import ROOT

STORE = Path(os.environ.get("LEO_DASHBOARD_DATA", ROOT / "runs/dashboard")).resolve()
STORE.mkdir(parents=True, exist_ok=True)
DB = STORE / "index.sqlite3"
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


def connection():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, record TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY, record TEXT NOT NULL)"
    )
    return db


def save(record):
    with connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO runs VALUES(?,?)",
            (record["id"], json.dumps(record)),
        )


def all_runs():
    with connection() as db:
        return [
            json.loads(row["record"])
            for row in db.execute("SELECT record FROM runs ORDER BY rowid DESC")
        ]


def get_run(run_id):
    with connection() as db:
        row = db.execute("SELECT record FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Run not found")
    return json.loads(row["record"])


def directory(run_id):
    get_run(run_id)
    return STORE / run_id


class Supervisor:
    def __init__(self):
        self.stop = Event()
        self.process = None
        self.active = None

    def start(self):
        for r in all_runs():
            if r["status"] not in TERMINAL:
                r.update(
                    status="interrupted",
                    error="Application restarted before the worker completed",
                )
                save(r)
        self.thread = Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stop.wait(0.2):
            queued = list(reversed([r for r in all_runs() if r["status"] == "queued"]))
            if not queued:
                continue
            record = queued[0]
            run_id = record["id"]
            d = STORE / run_id
            if read_json(d / "command.json", {}).get("command") == "cancel":
                continue
            record.update(status="preparing")
            save(record)
            with (d / "worker.log").open("w") as log:
                self.active = run_id
                self.process = subprocess.Popen(
                    [sys.executable, "-m", "dashboard.worker", str(d)],
                    cwd=ROOT,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                while self.process.poll() is None and not self.stop.wait(0.2):
                    state = read_json(d / "ui-state.json", {})
                    record = get_run(run_id)
                    if (
                        record["status"] == "cancelled"
                        or read_json(d / "command.json", {}).get("command") == "cancel"
                    ):
                        self.terminate()
                        break
                    record.update(
                        status=state.get("status", "preparing"),
                        progress=state.get("time_s", 0) / record["duration_s"],
                        metrics=state.get("frame", {}).get("metrics"),
                        error=state.get("error"),
                        wall_seconds=state.get("wall_seconds", 0),
                    )
                    save(record)
                code = self.process.poll()
                record = get_run(run_id)
                state = read_json(d / "ui-state.json", {})
                if read_json(d / "command.json", {}).get("command") == "cancel":
                    record["status"] = "cancelled"
                if record["status"] != "cancelled":
                    record.update(
                        status="completed"
                        if code == 0 and (d / "replay.json").exists()
                        else "interrupted"
                        if self.stop.is_set()
                        else "failed",
                        error=state.get("error") if code else None,
                    )
                if (d / "replay.json").exists():
                    record["metrics"] = read_json(d / "replay.json")["frames"][-1][
                        "metrics"
                    ]
                save(record)
                self.process = None
                self.active = None

    def terminate(self):
        if self.process and self.process.poll() is None:
            process = self.process
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            except ProcessLookupError:
                pass

    def shutdown(self):
        self.stop.set()
        self.terminate()
        self.thread.join(timeout=5)


supervisor = Supervisor()


@asynccontextmanager
async def lifespan(app):
    supervisor.start()
    yield
    supervisor.shutdown()


app = FastAPI(title="APOGEE Mission Control", version="1.0.0", lifespan=lifespan)


@app.exception_handler(KeyError)
async def missing_field(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"detail": f"Missing required field: {exc.args[0]}"}, status_code=422
    )


@app.exception_handler(ValueError)
async def invalid(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.get("/api/v1/capabilities")
def capabilities():
    python = os.environ.get("LEO_NS3_PYTHON", str(ROOT / ".venv-ns3/bin/python"))
    return dict(
        version="1.0.0",
        policies=POLICIES,
        engine_available=Path(python).exists(),
        training_available=False,
        observation_version=1,
        action_version=1,
    )


@app.get("/api/v1/scenarios")
def scenarios():
    items = [
        dict(id=p.stem, name=p.stem.replace("_", " ").title(), scenario=read_json(p))
        for p in sorted((ROOT / "scenarios/phase5").glob("*.json"))
    ]
    with connection() as db:
        items += [
            json.loads(r["record"]) for r in db.execute("SELECT record FROM scenarios")
        ]
    return items


@app.post("/api/v1/scenarios", status_code=201)
def scenario_save(body: dict):
    c = body["scenario"]
    check_limits(c)
    digest = hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()[:20]
    record = dict(id=digest, name=body.get("name", "Custom constellation"), scenario=c)
    with connection() as db:
        db.execute(
            "INSERT OR IGNORE INTO scenarios VALUES(?,?)", (digest, json.dumps(record))
        )
    return record


@app.post("/api/v1/previews")
def preview_scenario(body: dict):
    return preview(body["scenario"])


@app.get("/api/v1/runs")
def runs():
    return all_runs()


@app.get("/api/v1/runs/{run_id}")
def get(run_id: str):
    r = get_run(run_id)
    job = read_json(directory(run_id) / "job.json", {})
    return {**r, **({"scenario": job["scenario"]} if "scenario" in job else {})}


@app.post("/api/v1/runs", status_code=202)
def create_run(body: dict):
    c = body["scenario"]
    check_limits(c)
    policy = body.get("policy", "predictive")
    if policy not in {p["id"] for p in POLICIES}:
        raise ValueError("Unknown or unavailable policy; learned policies are deferred")
    run_id = uuid.uuid4().hex
    d = STORE / run_id
    d.mkdir()
    digest = hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
    r = dict(
        id=run_id,
        name=str(body.get("name", "Untitled mission"))[:100],
        status="queued",
        policy=policy,
        created_at=datetime.now(timezone.utc).isoformat(),
        duration_s=c["duration_s"],
        scenario_hash=digest,
        metrics=None,
        progress=0,
    )
    atomic_json(d / "job.json", {**r, "scenario": c})
    save(r)
    return r


@app.post("/api/v1/runs/{run_id}/commands", status_code=202)
def command(run_id: str, body: dict):
    r = get_run(run_id)
    c = body.get("command")
    if c not in ("pause", "resume", "cancel"):
        raise ValueError("Unknown command")
    if r["status"] in TERMINAL:
        raise HTTPException(409, "This run is already terminal")
    if c == "cancel":
        atomic_json(directory(run_id) / "command.json", dict(command="cancel"))
        if supervisor.active == run_id:
            supervisor.terminate()
        r.update(status="cancelled", command_requested=None)
        save(r)
    else:
        atomic_json(directory(run_id) / "command.json", dict(command=c))
        r["command_requested"] = c
        save(r)
    return r


@app.get("/api/v1/runs/{run_id}/stream")
async def stream(run_id: str, request: Request):
    get_run(run_id)

    async def events():
        last = None
        while not await request.is_disconnected():
            r = get_run(run_id)
            state = read_json(directory(run_id) / "ui-state.json", {})
            sequence = state.get("sequence", 0)
            key = (sequence, r["status"])
            if key != last:
                payload = dict(
                    run=r,
                    sequence=sequence,
                    frame=state.get("frame"),
                    nodes=state.get("nodes"),
                    events=state.get("events", []),
                )
                yield f"id: {sequence}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                last = key
            if r["status"] in TERMINAL:
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def replay_data(run_id: str):
    r = get_run(run_id)
    d = directory(run_id)
    bundle = read_json(d / "replay.json")
    if bundle:
        return bundle
    job = read_json(d / "job.json")
    frames = []
    if (d / "frames.jsonl").exists():
        for line in (d / "frames.jsonl").read_text().splitlines():
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not frames or frames[-1]["time_s"] <= 0:
        raise HTTPException(
            409,
            "This job ended before simulation time advanced; no replay is available",
        )
    state = read_json(d / "ui-state.json", {})
    return dict(
        schema_version=1,
        id=run_id,
        name=r["name"],
        status=r["status"],
        policy=r["policy"],
        scenario=job["scenario"],
        nodes=state.get("nodes", []),
        duration_s=frames[-1]["time_s"],
        configured_duration_s=r["duration_s"],
        frames=frames,
        events=state.get("events", []),
        frame="ECEF",
        units="km",
        source="Partial recorded simulation",
        scenario_hash=r["scenario_hash"],
        capabilities=dict(metrics=True, geometry=True, forecast=False),
    )


@app.get("/api/v1/runs/{run_id}/replay")
def replay(run_id: str, center_s: float | None = None, limit: int = 160):
    """A bounded overview or a contiguous frame window around the seek cursor."""
    import math
    from bisect import bisect_right

    if not 2 <= limit <= 160:
        raise ValueError("Replay window limit must be between 2 and 160")
    if center_s is not None and not math.isfinite(center_s):
        raise ValueError("Replay cursor must be finite")
    bundle = replay_data(run_id)
    frames = bundle["frames"]
    total = len(frames)
    if total <= limit:
        selected = frames
    elif center_s is None:
        selected = [frames[round(i * (total - 1) / (limit - 1))] for i in range(limit)]
    else:
        index = bisect_right([f["time_s"] for f in frames], center_s) - 1
        start = max(0, min(total - limit, index - limit // 3))
        selected = frames[start : start + limit]
    return {
        **bundle,
        "frames": selected,
        "total_frames": total,
        "sampled": center_s is None and total > limit,
    }


@app.get("/api/v1/imports/candidates")
def candidates():
    return [
        dict(path=str(p.parent.relative_to(ROOT / "runs")), name=p.parent.name)
        for p in (ROOT / "runs").rglob("results.json")
        if STORE not in p.parents
    ][:500]


@app.post("/api/v1/imports", status_code=201)
def import_run(body: dict):
    run_id = uuid.uuid4().hex
    if "bundle" in body:
        bundle = body["bundle"]
        validate_bundle(bundle)
        bundle["id"] = run_id
    else:
        path = (ROOT / "runs" / str(body.get("path", ""))).resolve()
        if not path.is_relative_to((ROOT / "runs").resolve()):
            raise ValueError("Imports must stay inside the runs directory")
        bundle = build_replay(path, run_id)
    fingerprint = hashlib.sha256(
        json.dumps(
            {k: v for k, v in bundle.items() if k not in ("id", "name", "bundled")},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = next(
        (r for r in all_runs() if r.get("import_hash") == fingerprint), None
    )
    if existing:
        return existing
    d = STORE / run_id
    d.mkdir()
    atomic_json(d / "replay.json", bundle)
    r = dict(
        id=run_id,
        name=bundle["name"],
        policy=bundle.get("policy", "unknown"),
        status=bundle["status"],
        created_at=datetime.now(timezone.utc).isoformat(),
        duration_s=bundle["duration_s"],
        scenario_hash=bundle.get("scenario_hash"),
        import_hash=fingerprint,
        metrics=bundle["frames"][-1].get("metrics"),
        progress=1,
    )
    save(r)
    return r


@app.get("/api/v1/runs/{run_id}/export")
def export(run_id: str):
    bundle = replay_data(run_id)
    path = directory(run_id) / "export.json"
    atomic_json(path, bundle)
    return FileResponse(path, filename=f"leo-{run_id[:8]}.json")


DIST = ROOT / "web/dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="mission-control")
