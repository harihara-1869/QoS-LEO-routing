# APOGEE Mission Control

The frontend is implemented with a working local Python API and isolated ns-3 worker. Phase 5 learning is still deferred. This is the dashboard implementation record; release acceptance is tracked in [REMAINING_WORK.md](../REMAINING_WORK.md).

## Start it

```bash
docker compose up --build
```

Open http://localhost:8080. The standalone `docker-compose up --build` launcher works too. Compose publishes only to `127.0.0.1`; no cloud account is needed. The first build requires internet access; built images, textures, fonts and recorded demos support subsequent `docker compose up --no-build` startup offline. Docker must provide Linux x86_64 containers; Apple Silicon uses emulation. Linux container execution is verified; native Windows/macOS host execution is not claimed as tested.

Stop with Ctrl+C or `docker compose down`. The host `runs/` mount retains the SQLite index and artifacts. A run interrupted by application shutdown is marked interrupted on restart. Closing a browser leaves the simulation running; reopening reconnects to the active job. One simulation runs at a time; additional jobs queue.

Optional configuration: `LEO_DASHBOARD_PORT` (default 8080) and `LEO_RUNS_DIR` (default `./runs`). Keep the run directory writable by the container user. Linux users who prefer host-owned files can run Compose with their UID/GID through an override.

### Native development

Install the simulator's two environments using the main README first, then:

```bash
.venv/bin/pip install -r requirements/dashboard.txt
npm ci --prefix web
npm run build --prefix web
.venv/bin/python -m dashboard
```

Open http://127.0.0.1:8000. Node 24 was used. For frontend hot reload, run `npm run dev --prefix web` in another terminal and open the Vite URL; it proxies `/api` to port 8000. The API serves the production build directly after `npm run build`.

## What works

- An interactive, locally textured Earth with backend-derived ECEF satellite/station positions, physical link segments, installed class routes, orbit guides, selection and a 2D fallback. Reduced-motion preferences disable automatic playback/camera rotation.
- Constellation Studio edits orbital parameters, epochs, physical terminals/capacities/timing, ground stations, traffic, packet settings and forecast parameters. JSON import/export and immutable named revisions preserve the simulator scenario format. Preview uses the authoritative orbital model; packet metrics remain unavailable in preview. Edits affect the next launch.
- Launch freezes a scenario into a durable job. The isolated worker runs the existing packet engine. Engine pause/resume acknowledges a control boundary; Pause view/Catch up only change presentation. Cancellation targets the owned worker process group, including ns-3. Completed and partial recorded runs remain in history.
- Live cumulative UDP delivery/drop/in-flight accounting, survivor-only p95 delay, deadline success with pending outcomes censored, application-byte goodput and per-class metrics. TCP bytes contribute to goodput, never to UDP datagram counters. Wall time and simulation time are separate.
- Search/status filtering, existing artifact-directory import, portable JSON bundle import/export, replay speed/scrubbing, topology-event navigation and browser-local bookmarks. Exports retain complete frame data. Browser requests return bounded overviews or contiguous detailed windows, rather than loading the original large control logs.
- Comparison uses explicit simulation-second or relative-episode alignment and reports source configuration differences. It shows cursor outcomes plus final Bulk fairness/service-gap summaries when available. Inspect mission B switches the shared globe.
- Presentation mode, responsive layouts, locally bundled fonts/textures and two matched real offline runs. Six implemented heuristic policies are registered. A future learned adapter can request a checkpoint manifest ID through the same launch surface; no trained model or training chart is claimed.

## Mentor walkthrough (3–5 minutes)

1. Open the saved **Aurora · Predictive handover** replay (`demo-handover`). Pause playback, select a station and inspect a flow's installed route. These are real recorded ns-3 outcomes.
2. Open Studio. Change altitude, station coordinates or a traffic rate and generate a preview. Explain that the preview propagates geometry without simulating packets. Use a short duration when launching live; simulation seconds are not wall seconds.
3. Launch a mission, then demonstrate engine pause versus Pause view. Refresh once to show browser reconnection. Open the library when it completes.
4. Reopen the bundled replay. Seek to the topology transitions at **3.90 s** (link removed) and **4.10 s** (link established). Bookmark either cursor; bookmarks are kept in this browser and do not alter source artifacts.
5. Compare `demo-handover` with **Aurora · Propagation baseline** (`demo-baseline`). Scenario hashes match. Both retain the unfavorable Control deadline result; predictive routing is not a guarantee of feasibility. Use final summaries only as whole-episode results, separate from cursor metrics.

The bundled sources are `runs/fidelity/evaluation/normal_predictive` and `normal_propagation`. Each normalized replay retains the original result/source/scenario hashes. Regenerate from the original artifacts with:

```bash
.venv/bin/python -m dashboard.export_demo
.venv/bin/python -m dashboard.export_demo --run runs/fidelity/evaluation/normal_propagation --id demo-baseline --name "Aurora · Propagation baseline" --output web/public/data/baseline.json
```

## Verification

- Simulator regression suite: 93 tests passed after the integration; three additional dashboard tests subsequently passed for ECEF station geography, final saved-class reconciliation and bounded replay/import validation.
- Frontend: TypeScript/production build and six cursor/configuration tests pass.
- Chromium: Studio editing, bundle import, replay, comparison, mobile layout, real launch/pause/resume/reconnect/cancel/history, offline assets, reduced motion, bookmarks, presentation, automatic WebGL failure fallback and a test-only future checkpoint adapter.
- The packaged container passed real-engine browser tests; completed and cancelled partial history survived container replacement, and no simulation child remained after cancellation.
- Visual review: desktop, mobile, Studio, comparison and presentation screenshots. Responsive checks cover 1366×768, 1440×900, 1920×1080 and 390×844 with no horizontal overflow.
- Observer enabled/disabled packet results agree. Bundled final per-class counts, p95 and deadline success reconcile with the authoritative QoS summaries.

Run checks from the repository root:

```bash
.venv/bin/pip install httpx==0.28.1
.venv/bin/python -m unittest discover -s tests -v
npm test --prefix web
npm run build --prefix web
npm exec --prefix web -- playwright install chromium
npm run test:browser --prefix web
npm run test:compatibility --prefix web
npm run test:live --prefix web
```

The browser scripts require the local API and frontend to be running. `LEO_TEST_URL` can point them at the packaged app; `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` optionally selects an already installed Chromium. Live tests create named test runs in that server's library; use a separate run directory for isolated verification. Test HTTP tooling is separate from runtime dependencies.

## Release follow-up

The frontend and local integration are implemented. Phase 5 remains deferred until the dashboard release gate passes. [REMAINING_WORK.md](../REMAINING_WORK.md) is the maintained checklist and assigns all remaining areas to four contributors; no further implementation is assigned to harihara1869.
