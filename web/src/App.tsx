import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Clock3,
  FolderClock,
  GitCompareArrows,
  Info,
  Layers3,
  MapPin,
  Moon,
  Orbit,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Satellite,
  Sun,
  TriangleAlert,
  Waypoints,
  X,
  Presentation,
} from "lucide-react";
import type {
  Capabilities,
  LiveSnapshot,
  Replay,
  RunRecord,
  Scenario,
  View,
} from "./lib/types";
import { api, download } from "./lib/api";
import {
  flowTimingError,
  format,
  frameAt,
  utcClock,
} from "./lib/model";
import { Studio } from "./components/Studio";
import { Library } from "./components/Library";
import { Sparkline, DeadlineTracker, QueueBreakdown, RouteChurnCounter } from "./components/Charts";
const Globe = lazy(() => import("./components/Globe"));
const tabs: { id: View; label: string; icon: typeof Orbit }[] = [
  { id: "mission", label: "Mission control", icon: Orbit },
  { id: "studio", label: "Constellation studio", icon: Layers3 },
  { id: "library", label: "Run library", icon: FolderClock },
  { id: "compare", label: "Compare runs", icon: GitCompareArrows },
  { id: "policies", label: "Policy lab", icon: Waypoints },
];
const fallbackPolicies = [
  ["propagation", "Propagation Dijkstra"],
  ["congestion", "Congestion-aware Dijkstra"],
  ["qos_current", "Current-state QoS"],
  ["lifetime", "Link lifetime"],
  ["queue_forecast", "Queue forecast"],
  ["predictive", "Predictive QoS"],
].map(([id, label]) => ({
  id,
  label,
  kind: "heuristic" as const,
  available: true,
  checkpoint_required: false,
  observation_version: 1,
  action_version: 1,
}));
const terminal = new Set(["completed", "cancelled", "failed", "interrupted"]);

// Overview charts stay bounded; detailed discrete state is loaded near the cursor.
function useReplayWindow(run: Replay | undefined, time: number, live: boolean) {
  const [window, setWindow] = useState<Replay>();
  const bucket = Math.floor(time / 5);
  useEffect(() => {
    let stale = false;
    if (run?.sampled && !live)
      api
        .window(run.id, time)
        .then((value) => {
          if (!stale) setWindow(value);
        })
        .catch(() => {});
    return () => {
      stale = true;
    };
  }, [run?.id, run?.sampled, bucket, live]);
  const frames = window?.frames;
  return window?.id === run?.id &&
    frames?.length &&
    time >= frames[0].time_s &&
    time <= frames[frames.length - 1].time_s
    ? window
    : run;
}

function App() {
  const [run, setRun] = useState<Replay>(),
    [draft, setDraft] = useState<Scenario>(),
    [view, setView] = useState<View>("mission"),
    [time, setTime] = useState(1.25),
    [playing, setPlaying] = useState(
      () => !matchMedia("(prefers-reduced-motion: reduce)").matches,
    ),
    [selected, setSelected] = useState<number | null>(null),
    [speed, setSpeed] = useState(0.25),
    [flow, setFlow] = useState(1),
    [links] = useState(true),
    [orbits] = useState(true),
    [rotate] = useState(true),
    [flat] = useState(false),
    [focusPath, setFocusPath] = useState(false),
    [reset] = useState(0),
    [presentation, setPresentation] = useState(false),
    [placing, setPlacing] = useState(false),
    [theme, setTheme] = useState<"light" | "dark">(() => {
      try {
        return (localStorage.getItem("apogee-theme") as "light" | "dark") || "light";
      } catch {
        return "light";
      }
    });

  useEffect(() => {
    try {
      localStorage.setItem("apogee-theme", theme);
    } catch {}
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const [cap, setCap] = useState<Capabilities>(),
    [online, setOnline] = useState(false),
    [records, setRecords] = useState<RunRecord[]>([]),
    [presets, setPresets] = useState<
      { id: string; name: string; scenario: Scenario }[]
    >([]),
    [policy, setPolicy] = useState("predictive"),
    [busy, setBusy] = useState(false),
    [toast, setToast] = useState(""),
    [launchOpen, setLaunchOpen] = useState(false),
    [checkpoint, setCheckpoint] = useState(""),
    [name, setName] = useState("Aurora · Custom mission"),
    [live, setLive] = useState<RunRecord>(),
    [followLive, setFollowLive] = useState(true),
    [compared, setCompared] = useState<string[]>([]),
    [comparison, setComparison] = useState<Replay>(),
    [bootError, setBootError] = useState(""),
    [baseline, setBaseline] = useState<Replay>(),
    [demoStep, setDemoStep] = useState<number | null>(null);
  const [bookmarks] = useState<
    Record<string, import("./lib/types").RunEvent[]>
  >(() => {
    try {
      return JSON.parse(localStorage.getItem("apogee-bookmarks") ?? "{}");
    } catch {
      return {};
    }
  });
  const launchReturn = useRef<HTMLElement | null>(null);
  function openLaunch() {
    launchReturn.current = document.activeElement as HTMLElement;
    setLaunchOpen(true);
  }
  useEffect(() => {
    if (!launchOpen) launchReturn.current?.focus();
  }, [launchOpen]);
  useEffect(() => {
    try {
      localStorage.setItem("apogee-bookmarks", JSON.stringify(bookmarks));
    } catch {
      /* Browser storage may be disabled. */
    }
  }, [bookmarks]);
  useEffect(() => {
    try {
      localStorage.setItem("apogee-theme", theme);
    } catch {
      /* Browser storage may be disabled. */
    }
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  const stream = useRef<EventSource | null>(null),
    previewGeneration = useRef(0),
    previewAbort = useRef<AbortController | null>(null),
    demo = useRef<Replay | undefined>(undefined),
    toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const notify = useCallback((message: string) => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 6500);
  }, []);
  const refresh = useCallback(() => {
    api
      .runs()
      .then(setRecords)
      .catch(() => {});
  }, []);
  useEffect(() => {
    let disposed = false;
    fetch("/data/demo.json")
      .then((r) => {
        if (!r.ok) throw Error("The offline demonstration could not load");
        return r.json();
      })
      .then((r: Replay) => {
        if (disposed) return;
        demo.current = r;
        setRun((previous) => previous ?? r);
        setDraft((previous) => previous ?? structuredClone(r.scenario));
        setPresets((previous) =>
          previous.length
            ? previous
            : [
                {
                  id: "normal",
                  name: "Aurora · Congestion + handover",
                  scenario: r.scenario,
                },
              ],
        );
        setSelected(r.nodes.find((n) => n.name === "GS_INDIA")?.id ?? null);
      })
      .catch((e) => setBootError(String(e)));
    fetch("/data/baseline.json")
      .then((r) => {
        if (!r.ok) throw Error("Baseline unavailable");
        return r.json();
      })
      .then((r: Replay) => {
        if (!disposed) setBaseline(r);
      })
      .catch(() => {});
    api
      .capabilities()
      .then((c) => {
        if (disposed) return;
        setCap(c);
        setOnline(true);
        api.runs().then((rows) => {
          if (disposed) return;
          setRecords(rows);
          const active =
            rows.find(
              (r) => !terminal.has(r.status) && r.status !== "queued",
            ) ?? rows.find((r) => r.status === "queued");
          if (active)
            api.run(active.id).then((r) => {
              if (!disposed && r.scenario) startStream(r, r.scenario);
            });
        });
        api
          .presets()
          .then((rows) => {
            if (!disposed) setPresets(rows);
          })
          .catch(() => {});
      })
      .catch(() => setOnline(false));
    return () => {
      disposed = true;
      stream.current?.close();
      clearTimeout(toastTimer.current);
    };
  }, [refresh]);
  useEffect(() => {
    if (!playing || !run || (live && followLive && !terminal.has(live.status)))
      return;
    let last = performance.now();
    const id = setInterval(() => {
      const now = performance.now(),
        delta = Math.min(0.3, (now - last) / 1000);
      last = now;
      setTime((t) => {
        const next = Math.min(run.duration_s, t + delta * speed);
        if (next >= run.duration_s) setPlaying(false);
        return next;
      });
    }, 50);
    return () => clearInterval(id);
  }, [playing, speed, run?.duration_s, live?.status, followLive]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLaunchOpen(false);
        setPresentation(false);
        setPlacing(false);
                return;
      }
      if (e.key === "Tab") {
        const modal = document.querySelector<HTMLElement>("[role=dialog]");
        if (modal) {
          const items = [
            ...modal.querySelectorAll<HTMLElement>(
              "button:not(:disabled),input,select,textarea,a[href]",
            ),
          ];
          const first = items[0],
            last = items.at(-1);
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last?.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first?.focus();
          }
        }
      }
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      if (e.code === "Space") {
        e.preventDefault();
        setPlaying((v) => !v);
        if (live && !terminal.has(live.status)) setFollowLive((v) => !v);
      }
      if (e.key === "Escape") {
        setLaunchOpen(false);
        setPresentation(false);
        setPlacing(false);
              }
      if (e.key === "ArrowRight" && !(live && !terminal.has(live.status)))
        setTime((t) => Math.min(run?.duration_s ?? 0, t + 0.1));
      if (e.key === "ArrowLeft" && !(live && !terminal.has(live.status)))
        setTime((t) => Math.max(0, t - 0.1));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [run?.duration_s, live]);
  useEffect(() => {
    if (compared.length !== 2) {
      setComparison(undefined);
      return;
    }
    const other = compared.find((id) => id !== run?.id) ?? compared[1];
    loadReplay(other)
      .then(setComparison)
      .catch((e) => notify(String(e)));
  }, [compared.join("|"), run?.id]);
  async function loadReplay(id: string) {
    if (id === "demo-handover" && demo.current) return demo.current;
    if (id === "demo-baseline" && baseline) return baseline;
    return api.replay(id);
  }
  async function openRun(id: string) {
    setBusy(true);
    try {
      const active = records.find(
        (r) => r.id === id && !terminal.has(r.status),
      );
      if (active) {
        const r = await api.run(id);
        if (r.scenario) {
          startStream(r, r.scenario);
          setView("mission");
          return;
        }
      }
      const next = await loadReplay(id);
      stream.current?.close();
      setLive(undefined);
      setRun(next);
      setTime(0);
      setPlaying(false);
      setSelected(null);
      setFlow(next.scenario.flows[0]?.flow_id ?? 1);
      setView("mission");
          } catch (e) {
      notify(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function duplicate(id: string) {
    try {
      const r = await loadReplay(id);
      if (!r.scenario.constellation)
        throw Error(
          "This historical run has an explicit network graph. Import an orbital scenario in Studio to create a constellation.",
        );
      setDraft(structuredClone(r.scenario));
      setName(`${r.name} · copy`);
      setView("studio");
      notify("Configuration copied. The recorded mission is unchanged.");
    } catch (e) {
      notify(String(e));
    }
  }
  function startStream(record: RunRecord, config: Scenario) {
    stream.current?.close();
    const source = new EventSource(`/api/v1/runs/${record.id}/stream`);
    stream.current = source;
    setFollowLive(true);
    setLive(record);
    setPlaying(false);
    setTime(0);
    setRun({
      schema_version: 1,
      id: record.id,
      name: record.name,
      status: record.status,
      policy: record.policy,
      scenario: config,
      nodes: [],
      duration_s: config.duration_s,
      frames: [
        {
          time_s: 0,
          positions: [],
          links: [],
          metrics: null,
          routes: [],
          queues: [],
        },
      ],
      events: [],
      frame: "ECEF",
      units: "km",
      source: "Preparing the authoritative orbital model",
      capabilities: { metrics: false, geometry: false, forecast: false },
    });
    source.onmessage = (e) => {
      const s: LiveSnapshot = JSON.parse(e.data);
      setLive(s.run);
      setRun((previous) =>
        previous?.id === record.id
          ? { ...previous, status: s.run.status }
          : previous,
      );
      if (s.frame) {
        if (followRef.current)
          setRun((previous) => ({
            schema_version: 1,
            id: record.id,
            name: record.name,
            status: s.run.status,
            policy: record.policy,
            scenario: config,
            nodes: s.nodes ?? previous?.nodes ?? [],
            duration_s: config.duration_s,
            frames:
              previous?.id === record.id
                ? [
                    ...previous.frames
                      .filter((f) => f.time_s !== s.frame!.time_s)
                      .slice(-250),
                    s.frame!,
                  ]
                : [s.frame!],
            events: s.events ?? previous?.events ?? [],
            frame: "ECEF",
            units: "km",
            source: "Live ns-3 packet simulation",
            capabilities: { metrics: true, geometry: true, forecast: true },
            scenario_hash: record.scenario_hash,
          }));
        if (followRef.current) setTime(s.frame.time_s);
      }
      if (terminal.has(s.run.status)) {
        source.close();
        refresh();
        if (s.run.status === "completed") {
          api
            .replay(record.id)
            .then((r) => {
              setRun(r);
              if (followRef.current) setTime(r.duration_s);
              notify(
                "Mission complete. Every result is saved to your library.",
              );
            })
            .catch((e) => notify(String(e)));
        } else
          notify(
            s.run.error ??
              `Mission ${s.run.status}. Recorded data remains in the library.`,
          );
      }
    };
    source.onerror = () => {
      notify("Telemetry reconnecting. The simulation continues independently.");
    };
  }
  // The stream callback reads this ref so Pause view does not reset or stop a worker.
  const followRef = useRef(followLive);
  followRef.current = followLive;
  async function launch() {
    if (!draft || !online) return;
    const timing = flowTimingError(draft);
    if (timing) {
      notify(`${timing} Fix the flow timing in Studio before launching.`);
      setView("studio");
      return;
    }
    setBusy(true);
    try {
      const record = await api.launch(
        draft,
        policy,
        name.trim() || "Untitled mission",
        checkpoint || undefined,
      );
      setLaunchOpen(false);
      setView("mission");
      setLive(record);
      setTime(0);
      startStream(record, structuredClone(draft));
      notify("Mission queued. Preparing the orbital model and packet engine.");
      refresh();
    } catch (e) {
      notify(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function generatePreview() {
    if (!draft) return;
    if (!online) {
      notify(
        "Start the local API to generate authoritative orbital previews. You can still edit and export your design.",
      );
      return;
    }
    setBusy(true);
    previewAbort.current?.abort();
    const controller = new AbortController();
    previewAbort.current = controller;
    const generation = ++previewGeneration.current;
    try {
      const next = await api.preview(draft, controller.signal);
      if (generation !== previewGeneration.current) return;
      stream.current?.close();
      setLive(undefined);
      setRun(next);
      setTime(0);
      setPlaying(true);
      setSpeed(0.5);
      setSelected(null);
      notify(
        "Preview ready. Geometry only; no packet metrics have been simulated.",
      );
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError"))
        notify(String(e));
    } finally {
      if (generation === previewGeneration.current) setBusy(false);
    }
  }
  async function saveDesign() {
    if (!draft) return;
    try {
      if (online) {
        await api.saveScenario(draft, name);
        setPresets(await api.presets());
      } else {
        const saved = JSON.parse(
          localStorage.getItem("apogee-designs") ?? "[]",
        );
        saved.push({ name, scenario: draft });
        localStorage.setItem("apogee-designs", JSON.stringify(saved));
      }
      notify("Design saved as a separate revision.");
    } catch (e) {
      notify(String(e));
    }
  }
  function toggleCompare(id: string) {
    setCompared((ids) =>
      ids.includes(id)
        ? ids.filter((i) => i !== id)
        : ids.length < 2
          ? [...ids, id]
          : [ids[1], id],
    );
  }
  function place(lat: number, lon: number) {
    if (!draft) return;
    const c = structuredClone(draft);
    c.ground_stations.push([
      `GS_${c.ground_stations.length + 1}`,
      Number(lat.toFixed(4)),
      Number(lon.toFixed(4)),
      0,
    ]);
    setDraft(c);
    setPlacing(false);
    notify(
      "Ground station added to the design. Generate a preview to apply it.",
    );
  }
  async function presentationMode() {
    setPresentation((v) => !v);
    if (!presentation) {
      try {
        await document.documentElement.requestFullscreen();
      } catch {
        /* theatre layout still works */
      }
    } else if (document.fullscreenElement) await document.exitFullscreen();
  }
  const detailedRun = useReplayWindow(
    run,
    time,
    Boolean(live && !terminal.has(live.status)),
  );
  const current = frameAt(detailedRun, time),
    activeLive = Boolean(live && !terminal.has(live.status)),
    nodes = run?.nodes ?? [],
    policies = cap?.policies ?? fallbackPolicies;
  const policyLabel =
    policies.find((p) => p.id === run?.policy)?.label ??
    run?.policy?.replaceAll("_", " ") ??
    "—";
  const metrics = current?.metrics ?? run?.frames.at(-1)?.metrics ?? null;
  const delivered = metrics?.delivered;
  const dropped = metrics?.dropped;
  const inFlight = metrics?.in_flight;
  const generated = metrics?.generated;
  const demoRecord: RunRecord | undefined = demo.current
    ? {
        id: demo.current.id,
        name: demo.current.name,
        status: "completed",
        policy: "predictive",
        created_at: "",
        duration_s: demo.current.duration_s,
        scenario_hash: demo.current.scenario_hash,
        metrics: demo.current.frames.at(-1)?.metrics ?? null,
      }
    : undefined;
  const library = [
      ...(demoRecord ? [demoRecord] : []),
      ...(baseline
        ? [
            {
              id: baseline.id,
              name: baseline.name,
              status: baseline.status,
              policy: baseline.policy ?? "propagation",
              created_at: "",
              duration_s: baseline.duration_s,
              scenario_hash: baseline.scenario_hash,
              metrics: baseline.frames.at(-1)?.metrics ?? null,
            },
          ]
        : []),
      ...records,
    ],
    
    elapsed = run
      ? utcClock(run.scenario.epoch, (run.scenario.orbital_start_s ?? 0) + time)
      : "00:00:00.000";
  // ── Mentor demo walkthrough ──────────────────────────────────────────────
  const DEMO_STAGES = [
    {
      label: "1 / 5 · Constellation Studio",
      cue: "0:00 – 1:00",
      heading: "Welcome to APOGEE",
      body: "APOGEE models a 200-satellite Walker-delta LEO constellation with real SGP4 propagation and packet-level QoS routing. Use Constellation Studio (left sidebar) to inspect the orbital parameters, ground stations and traffic flows before running any simulation.",
      action: () => { setView("studio"); },
      actionLabel: "Open Studio",
    },
    {
      label: "2 / 5 · Conventional routing",
      cue: "1:00 – 2:00",
      heading: "Baseline: propagation Dijkstra",
      body: "This is the recorded baseline run using propagation-only Dijkstra routing. Seek to t ≈ 85 s to watch a link drop trigger a reactive reroute — notice the brief delivery dip as the new path is installed.",
      action: () => {
        openRun("demo-baseline").then(() => {
          setTime(85);
          setPlaying(false);
          setView("mission");
        });
      },
      actionLabel: "Load baseline & seek t=85 s",
    },
    {
      label: "3 / 5 · Predictive routing",
      cue: "2:00 – 3:30",
      heading: "APOGEE predictive controller",
      body: "The predictive run uses link-lifetime forecasting + queue-pressure EWMA to trigger a proactive handover ~75–80 s before the same link drop. Seek to t ≈ 76 s to compare: delivery stays above 90 % through the transition.",
      action: () => {
        openRun("demo-handover").then(() => {
          setTime(76);
          setPlaying(false);
          setView("mission");
        });
      },
      actionLabel: "Load demo & seek t=76 s",
    },
    {
      label: "4 / 5 · Side-by-side comparison",
      cue: "3:30 – 4:30",
      heading: "Compare view",
      body: "The Compare view plays both runs in sync so you can see the delivery ratio, queue pressure and route-churn delta side by side. The predictive controller fires its handover ~10–15 s earlier, trading a small extra route change for sustained throughput.",
      action: () => {
        setCompared(["demo-handover", "demo-baseline"]);
        openRun("demo-handover").then(() => setView("compare"));
      },
      actionLabel: "Open compare view",
    },
    {
      label: "5 / 5 · Honest limitations",
      cue: "4:30 – 5:00",
      heading: "Calibration & caveats",
      body: "• Queue-forecast EWMA error is worse than persistence under bursts/overload.\n• The 50 ms Control deadline is mostly infeasible at the stress link rate (10 Mbps ISL, 2 Mbps ground are design assumptions).\n• All gains are workload-dependent — do not generalise without recalibration on measured LENS data.",
      action: () => { setDemoStep(null); },
      actionLabel: "Close walkthrough",
    },
  ] as const;

  type DemoStage = (typeof DEMO_STAGES)[number];
  function runDemoStage(s: DemoStage) { s.action(); }

  if (bootError)
    return (
      <div className="boot-error">
        <img src="/assets/mark.svg" width="48" />
        <h1>Mission data could not load.</h1>
        <p>{bootError}</p>
        <button className="primary-button" onClick={() => location.reload()}>
          Retry connection
        </button>
      </div>
    );
  if (!run || !draft || !current)
    return (
      <div className="boot-screen">
        <img src="/assets/mark.svg" width="54" />
        <h1>APOGEE</h1>
        <div className="boot-line" />
        <span>Establishing an orbital perspective</span>
      </div>
    );
  const rotateEarth =
    rotate && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  const globeFallback = (
    <div className="globe-loading">
      <Orbit size={35} className="spin" />
      <span>Rendering the Earth</span>
    </div>
  );
  const globe = (
    <Suspense fallback={globeFallback}>
      <Globe
        run={detailedRun ?? run}
        time={time}
        selected={selected}
        onSelect={(id) => {
          setSelected(id);
        }}
        flow={flow}
        links={links}
        orbits={orbits}
        rotate={rotateEarth}
        presentation={presentation}
        placeStation={placing ? place : undefined}
        flat={flat}
        reset={reset}
        focusPath={focusPath}
      />
    </Suspense>
  );
  const studioTime =
    run.frames.find((frame) => frame.positions.length)?.time_s ?? 0;
  const studioGlobe = (
    <Suspense fallback={globeFallback}>
      <Globe
        run={run}
        time={studioTime}
        selected={null}
        onSelect={() => {}}
        flow={-1}
        links={false}
        orbits={orbits}
        rotate={rotateEarth}
        presentation={false}
        placeStation={placing ? place : undefined}
        flat={flat}
        reset={reset}
        focusPath={false}
        design
      />
    </Suspense>
  );
  const classSuccess = (
    key: "CONTROL" | "REALTIME" | "BULK",
  ): number | null => {
    const data = metrics?.classes?.[key];
    if (!data) return null;
    const ratio =
      data.deadline_success ??
      (data.generated > 0 ? data.delivered / data.generated : null);
    return ratio == null ? null : Math.min(100, Math.max(0, ratio * 100));
  };
  const classPercent = (key: "CONTROL" | "REALTIME" | "BULK") => {
    const value = classSuccess(key);
    return value != null ? `${value.toFixed(1)}%` : "—";
  };
  return (
    <div className={`app ${theme === "light" ? "light-theme" : ""} ${presentation ? "presentation" : ""}`}>
      <header className="app-header">
        <div
          className="logo"
          onClick={() => setView("mission")}
          aria-label="Apogee mission home"
        >
          <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.8">
            <ellipse cx="16" cy="16" rx="14" ry="6" transform="rotate(-28 16 16)" />
            <circle cx="16" cy="16" r="5" fill="var(--acc2)" />
            <circle cx="26" cy="9" r="1.8" fill="#b8660b" stroke="none" />
          </svg>
          <div>
            APOGEE<small>Orbital network lab</small>
          </div>
        </div>
        <nav id="nav">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={view === t.id ? "on" : ""}
              onClick={() => setView(t.id)}
            >
              {t.label}
              {t.id === "library" && library.length > 0 && (
                <span className="nav-badge">{library.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="hd-r">
          <span>
            <i className={`dot ${online ? "connected" : ""}`} />
            {online ? "Local system online" : "Offline replay"}
          </span>
          <span className="t">{elapsed} UTC</span>
          <button
            className="tg"
            title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
            aria-label="Toggle color theme"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
          >
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
          </button>
          <span className="user-avatar" title="Ayush Ranjan">
            A
          </span>
          <button className="btn pri" onClick={openLaunch}>
            <Plus size={14} />
            New simulation
          </button>
        </div>
      </header>

      <main id="main" className="main">
        {view === "library" ? (
          <Library
            runs={library}
            onOpen={openRun}
            onCompare={() => {
              if (compared[0])
                openRun(compared[0]).then(() => setView("compare"));
            }}
            selected={compared}
            onToggle={toggleCompare}
            onDuplicate={duplicate}
            onRefresh={refresh}
            notify={notify}
          />
        ) : view === "policies" ? (
          <section className="view">
            <div className="title-row">
              <div>
                <h1>One network. Different decisions.</h1>
                <p className="sub">
                  Inspect the implemented routing policies. Future learned
                  controllers use the same capability contract.
                </p>
              </div>
              <span className="badge">
                {policies.length} engineered baseline
                {policies.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="pol">
              {policies.map((p) => {
                const isSelected = policy === p.id;
                const desc =
                  (
                    {
                      propagation:
                        "Shortest paths weighted by current propagation delay.",
                      congestion:
                        "Balances propagation and observed directed queue pressure.",
                      qos_current:
                        "Current-state decisions with class-aware service safeguards.",
                      lifetime:
                        "Looks ahead to links approaching their usable lifetime.",
                      queue_forecast:
                        "Forecasts queue growth from recent arrival and service trends.",
                      predictive:
                        "Combines orbital forecasts, queue estimates and QoS safeguards.",
                    } as Record<string, string>
                  )[p.id] ?? "Deterministic routing policy implementation.";
                return (
                  <button
                    key={p.id}
                    className={`pc ${isSelected ? "sel" : ""}`}
                    onClick={() => {
                      setPolicy(p.id);
                      notify(`${p.label} selected`);
                    }}
                  >
                    <h3>{p.label}</h3>
                    <p>{desc}</p>
                    <small>
                      {isSelected
                        ? "✓ Selected"
                        : p.kind === "learned"
                          ? "Learned policy"
                          : "Heuristic policy"}
                    </small>
                  </button>
                );
              })}
            </div>
            <div className="later">
              <b>A place for learned intelligence.</b>
              Training and checkpoint inference are deferred until dashboard
              acceptance. The policy registry reserves versioned observations,
              actions and checkpoint compatibility. No trained model is active.
            </div>
          </section>
        ) : view === "compare" ? (
          (() => {
            const missionA = run;
            const secondId =
              compared.find((id) => id !== run.id) ??
              (library.find((r) => r.id !== run.id)?.id ?? run.id);
            const missionB =
              comparison && comparison.id === secondId
                ? comparison
                : (library.find((r) => r.id === secondId) ?? run);
            const metA = missionA.frames.at(-1)?.metrics ?? current?.metrics;
            const metB = "frames" in (missionB ?? {}) ? (missionB as Replay).frames.at(-1)?.metrics : (missionB as RunRecord)?.metrics;
            const delA =
              metA?.delivery_ratio != null ? metA.delivery_ratio * 100 : null;
            const delB =
              metB?.delivery_ratio != null ? metB.delivery_ratio * 100 : null;
            const latA =
              metA?.delay_p95_s != null ? metA.delay_p95_s * 1000 : null;
            const latB =
              metB?.delay_p95_s != null ? metB.delay_p95_s * 1000 : null;
            const gpA =
              metA?.goodput_bps != null ? metA.goodput_bps / 1e6 : null;
            const gpB =
              metB?.goodput_bps != null ? metB.goodput_bps / 1e6 : null;
            const latScale = Math.max(1, latA ?? 0, latB ?? 0);
            const gpScale = Math.max(1, gpA ?? 0, gpB ?? 0);
            const diffDel =
              delA != null && delB != null ? delA - delB : null;
            const diffLat =
              latA != null && latB != null ? latA - latB : null;
            const diffGp =
              gpA != null && gpB != null ? gpA - gpB : null;

            return (
              <section className="view">
                <div className="title-row">
                  <div>
                    <h1>Compare missions</h1>
                    <p className="sub">
                      Compare the conditions before comparing the outcomes.
                    </p>
                  </div>
                </div>
                <div
                  className="card panel"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "14px",
                    padding: "16px 20px",
                  }}
                >
                  <label>
                    Mission A
                    <select
                      className="sel"
                      value={missionA.id}
                      onChange={(e) => {
                        openRun(e.target.value);
                        setCompared([e.target.value, secondId]);
                      }}
                    >
                      {library.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Mission B
                    <select
                      className="sel"
                      value={secondId}
                      onChange={(e) => {
                        const id = e.target.value;
                        setCompared([missionA.id, id]);
                        api.replay(id).then(setComparison).catch(() => {});
                      }}
                    >
                      {library.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="cmp">
                  <div className="card panel">
                    <h3
                      style={{
                        fontSize: "16px",
                        color: "var(--ink)",
                        margin: "0 0 2px",
                      }}
                    >
                      {missionA.name}
                    </h3>
                    <span style={{ fontSize: "13px", color: "var(--mute)" }}>
                      {policies.find((p) => p.id === missionA.policy)?.label ??
                        missionA.policy}
                    </span>
                    <div className="met" style={{ marginTop: "14px" }}>
                      <div style={{ fontSize: "13px", color: "var(--mute)" }}>
                        Packet delivery
                      </div>
                      <div className="v win">
                        {delA != null ? delA.toFixed(1) : "—"}
                        <small>%</small>
                      </div>
                      <div className="bar">
                        <u
                          style={{
                            width: `${delA != null ? Math.min(100, delA) : 0}%`,
                            background: "var(--acc)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="met">
                      <div style={{ fontSize: "13px", color: "var(--mute)" }}>
                        Latency p95
                      </div>
                      <div className="v win">
                        {latA != null ? latA.toFixed(1) : "—"} <small>ms</small>
                      </div>
                      <div className="bar">
                        <u
                          style={{
                            width: `${latA != null ? Math.min(100, (latA / latScale) * 100) : 0}%`,
                            background: "var(--acc)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="met">
                      <div style={{ fontSize: "13px", color: "var(--mute)" }}>
                        Goodput
                      </div>
                      <div className="v win">
                        {gpA != null ? gpA.toFixed(2) : "—"} <small>Mbps</small>
                      </div>
                      <div className="bar">
                        <u
                          style={{
                            width: `${gpA != null ? Math.min(100, (gpA / gpScale) * 100) : 0}%`,
                            background: "var(--acc)",
                          }}
                        />
                      </div>
                    </div>
                  </div>
                  <div className="card panel">
                    <h3
                      style={{
                        fontSize: "16px",
                        color: "var(--ink)",
                        margin: "0 0 2px",
                      }}
                    >
                      {missionB.name}
                    </h3>
                    <span style={{ fontSize: "13px", color: "var(--mute)" }}>
                      {policies.find((p) => p.id === missionB.policy)?.label ??
                        missionB.policy}
                    </span>
                    <div className="met" style={{ marginTop: "14px" }}>
                      <div style={{ fontSize: "13px", color: "var(--mute)" }}>
                        Packet delivery
                      </div>
                      <div className="v">
                        {delB != null ? delB.toFixed(1) : "—"}
                        <small>%</small>
                      </div>
                      <div className="bar">
                        <u
                          style={{
                            width: `${delB != null ? Math.min(100, delB) : 0}%`,
                            background: "var(--mute)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="met">
                      <div style={{ fontSize: "13px", color: "var(--mute)" }}>
                        Latency p95
                      </div>
                      <div className="v">
                        {latB != null ? latB.toFixed(1) : "—"} <small>ms</small>
                      </div>
                      <div className="bar">
                        <u
                          style={{
                            width: `${latB != null ? Math.min(100, (latB / latScale) * 100) : 0}%`,
                            background: "var(--mute)",
                          }}
                        />
                      </div>
                    </div>
                    <div className="met">
                      <div style={{ fontSize: "13px", color: "var(--mute)" }}>
                        Goodput
                      </div>
                      <div className="v">
                        {gpB != null ? gpB.toFixed(2) : "—"} <small>Mbps</small>
                      </div>
                      <div className="bar">
                        <u
                          style={{
                            width: `${gpB != null ? Math.min(100, (gpB / gpScale) * 100) : 0}%`,
                            background: "var(--mute)",
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
                <div className="card delta">
                  <div>
                    <span style={{ fontSize: "13px", color: "var(--mute)" }}>
                      Delivery
                    </span>
                    <b>
                      {diffDel != null
                        ? `${diffDel >= 0 ? "+" : ""}${diffDel.toFixed(1)} pts`
                        : "—"}
                    </b>
                    <span style={{ fontSize: "12px", color: "var(--mute)" }}>
                      A relative to B
                    </span>
                  </div>
                  <div>
                    <span style={{ fontSize: "13px", color: "var(--mute)" }}>
                      Latency p95
                    </span>
                    <b
                      style={{
                        color:
                          diffLat == null
                            ? "var(--mute)"
                            : diffLat <= 0
                              ? "var(--acc)"
                              : "var(--bad)",
                      }}
                    >
                      {diffLat != null
                        ? `${diffLat >= 0 ? "+" : ""}${diffLat.toFixed(1)} ms`
                        : "—"}
                    </b>
                    <span style={{ fontSize: "12px", color: "var(--mute)" }}>
                      A relative to B
                    </span>
                  </div>
                  <div>
                    <span style={{ fontSize: "13px", color: "var(--mute)" }}>
                      Goodput
                    </span>
                    <b>
                      {diffGp != null
                        ? `${diffGp >= 0 ? "+" : ""}${diffGp.toFixed(2)} Mbps`
                        : "—"}
                    </b>
                    <span style={{ fontSize: "12px", color: "var(--mute)" }}>
                      A relative to B
                    </span>
                  </div>
                </div>
              </section>
            );
          })()
        ) : view === "studio" ? (
          <section className="view">
            <div className="title-row">
              <div>
                <h1>Constellation studio</h1>
                <p className="sub">
                  Shape an orbital network, then see it come to life.
                </p>
              </div>
              <button className="btn pri" onClick={openLaunch}>
                <Play size={14} />
                Launch simulation
              </button>
            </div>
            <div className="studio">
              <Studio
                scenario={draft}
                onChange={(c) => {
                  setDraft(c);
                  previewGeneration.current++;
                  previewAbort.current?.abort();
                }}
                presets={presets}
                onPreset={(c) => {
                  setDraft(c);
                  const pName =
                    presets.find(
                      (p) =>
                        JSON.stringify(p.scenario) === JSON.stringify(c),
                    )?.name ?? "Custom mission";
                  setName(
                    pName.startsWith("Aurora") ? pName : `Aurora · ${pName}`,
                  );
                }}
                onPreview={generatePreview}
                onSave={saveDesign}
                busy={busy}
                onPlace={() => setPlacing((v) => !v)}
                placing={placing}
              />
              <div className="card globe-card">
                {studioGlobe}
                <div className="g-tag">
                  <b>Orbital network</b>
                  <span>Drag to orbit, scroll to zoom</span>
                </div>
                <div className="g-stats">
                  <div>
                    <b>
                      {nodes.filter((n) => n.kind === "satellite").length}
                    </b>
                    <span>satellites</span>
                  </div>
                  <div>
                    <b>{draft.constellation?.n_planes ?? 0}</b>
                    <span>orbital planes</span>
                  </div>
                  <div>
                    <b>{nodes.filter((n) => n.kind === "ground").length}</b>
                    <span>stations</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        ) : (
          <section className="view">
            <div className="title-row">
              <div>
                <h1>
                  Mission control
                  <span className="badge">
                    {activeLive ? "Live telemetry" : "Saved replay"}
                  </span>
                </h1>
                <p className="sub">
                  {run.name}, running on the {policyLabel} policy.
                </p>
              </div>
              <button
                className="btn"
                onClick={() => {
                  if (run.id.startsWith("demo-") || run.status === "preview") {
                    download(run, `apogee-${run.id.slice(0, 10)}.json`);
                  } else {
                    const a = document.createElement("a");
                    a.href = `/api/v1/runs/${run.id}/export`;
                    a.download = "";
                    a.click();
                  }
                }}
              >
                <ArrowDownToLine size={14} />
                Export run
              </button>
            </div>

            <div className="grid-m">
              <div>
                <div className="card globe-card">
                  {globe}
                  <div className="g-tag">
                    <b>Earth, low orbit</b>
                    <span>
                      {(
                        run.scenario.constellation?.altitude_km ?? 550
                      ).toFixed(0)}{" "}
                      km above the surface
                    </span>
                  </div>
                  <div className="g-stats">
                    <div>
                      <b>
                        {nodes.filter((n) => n.kind === "satellite").length}
                      </b>
                      <span>satellites</span>
                    </div>
                    <div>
                      <b>{current?.links.length ?? 0}</b>
                      <span>active links</span>
                    </div>
                    <div>
                      <b>{nodes.filter((n) => n.kind === "ground").length}</b>
                      <span>stations</span>
                    </div>
                  </div>
                  <div className="g-ctrls">
                    <button
                      className={`g-btn ${focusPath ? "active" : ""}`}
                      onClick={() => setFocusPath((v) => !v)}
                      title="Filter to primary traffic path"
                    >
                      <Waypoints size={13} />
                      {focusPath ? "All links" : "Focus path"}
                    </button>
                    <button
                      className={`g-btn ${presentation ? "active" : ""}`}
                      onClick={() => setPresentation((v) => !v)}
                      title="Clean presentation view"
                    >
                      <Presentation size={13} />
                      Demo view
                    </button>
                  </div>
                </div>

                <div className="card tl">
                  <button
                    className="play"
                    aria-label={playing ? "Pause" : "Play"}
                    onClick={() => {
                      if (time >= run.duration_s) setTime(0);
                      setPlaying((v) => !v);
                    }}
                  >
                    {playing ? <Pause size={16} /> : <Play size={16} />}
                  </button>
                  <input
                    type="range"
                    min={0}
                    max={run.duration_s}
                    step={0.01}
                    value={time}
                    onChange={(e) => {
                      setTime(Number(e.target.value));
                      setPlaying(false);
                    }}
                    aria-label="Mission timeline"
                  />
                  <output>
                    {time.toFixed(2)} / {run.duration_s.toFixed(2)} s
                  </output>
                </div>
              </div>

              <aside className="card tele">
                <h3>Packet delivery</h3>
                <div className="big">
                  {format.percent(metrics?.delivery_ratio)}
                </div>
                <div
                  style={{
                    color: "var(--mute)",
                    fontSize: "13px",
                    marginBottom: "10px",
                  }}
                >
                  {format.number(delivered)} delivered of{" "}
                  {format.number(generated)} generated
                </div>

                <div className="row2">
                  <div>
                    <h3>Latency p95</h3>
                    <div className="mid">
                      {metrics?.delay_p95_s != null
                        ? (metrics.delay_p95_s * 1000).toFixed(1)
                        : "—"}{" "}
                      <small>ms</small>
                    </div>
                  </div>
                  <div>
                    <h3>Goodput</h3>
                    <div className="mid">
                      {metrics?.goodput_bps != null
                        ? (metrics.goodput_bps / 1e6).toFixed(2)
                        : "—"}{" "}
                      <small>Mbps</small>
                    </div>
                  </div>
                </div>

                <div className="cnt">
                  <div>
                    {format.number(delivered)}
                    <small>delivered</small>
                  </div>
                  <div>
                    {format.number(dropped)}
                    <small>dropped</small>
                  </div>
                  <div>
                    {format.number(inFlight)}
                    <small>in flight</small>
                  </div>
                </div>

                <h3>Service classes</h3>
                <div className="cls">
                  <div>
                    <div className="cls-head">
                      <span>
                        Control<em>deadline success</em>
                      </span>
                      <i>{classPercent("CONTROL")}</i>
                    </div>
                    <div className="bar">
                      <u
                        style={{ width: `${classSuccess("CONTROL") ?? 0}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="cls-head">
                      <span>
                        Realtime<em>deadline success</em>
                      </span>
                      <i>{classPercent("REALTIME")}</i>
                    </div>
                    <div className="bar">
                      <u
                        style={{ width: `${classSuccess("REALTIME") ?? 0}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="cls-head">
                      <span>
                        Bulk<em>delivery</em>
                      </span>
                      <i>{classPercent("BULK")}</i>
                    </div>
                    <div className="bar">
                      <u
                        style={{ width: `${classSuccess("BULK") ?? 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              </aside>
            </div>

            <div className="charts">
              <div className="card panel">
                <h3>Latency over time</h3>
                <b>p95, cumulative</b>
                <Sparkline
                  values={run.frames.flatMap((frame) =>
                    frame.metrics?.delay_p95_s != null
                      ? [frame.metrics.delay_p95_s * 1000]
                      : [],
                  )}
                  color="var(--acc)"
                />
              </div>
              <div className="card panel">
                <h3>Network goodput</h3>
                <b>run-window average</b>
                <Sparkline
                  values={run.frames.flatMap((frame) =>
                    frame.metrics?.goodput_bps != null
                      ? [frame.metrics.goodput_bps / 1e6]
                      : [],
                  )}
                  color="var(--acc)"
                />
              </div>
              <div className="card panel">
                <h3>Events and topology</h3>
                <ul className="ev">
                  {run.events?.length ? (
                    run.events.slice(-3).map((e, i) => (
                      <li key={i}>
                        <span>{e.time_s.toFixed(2)} s</span>
                        {e.title}
                        <small>{e.detail ?? "transition"}</small>
                      </li>
                    ))
                  ) : (
                    <li className="ev-empty">
                      No topology transitions recorded in this run.
                    </li>
                  )}
                </ul>
              </div>
            </div>

            <div className="extra-charts">
              <div className="card panel">
                <h3>QoS deadline compliance</h3>
                <b>Service-class latency SLAs</b>
                <DeadlineTracker metrics={metrics} scenario={run.scenario} />
              </div>
              <div className="card panel">
                <h3>Queue buffer occupancy</h3>
                <b>Total satellite queue pressure</b>
                <QueueBreakdown
                  queues={current?.queues ?? []}
                  links={current?.links ?? []}
                />
              </div>
              <div className="card panel">
                <h3>Route stability</h3>
                <b>Path changes & handover churn</b>
                <RouteChurnCounter events={run.events ?? []} policy={policyLabel} />
              </div>
            </div>
          </section>
        )}
      </main>

      {presentation && (
        <button
          className="exit-presentation secondary-button"
          onClick={presentationMode}
        >
          <X size={14} />
          Exit presentation
        </button>
      )}
      {launchOpen && (
        <div className="modal-backdrop" onClick={() => setLaunchOpen(false)}>
          <div
            className="modal launch-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="launch-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close-btn"
              aria-label="Close launch"
              onClick={() => setLaunchOpen(false)}
            >
              <X size={16} />
            </button>
            <div className="modal-eyebrow">
              <Orbit size={16} style={{ color: "var(--acc)" }} />
              <span>A NEW ORBITAL EXPERIMENT</span>
            </div>
            <h2 id="launch-title" style={{ margin: "4px 0 6px", fontSize: "22px", letterSpacing: "-0.02em" }}>
              Ready for launch.
            </h2>
            <p className="sub" style={{ margin: "0 0 16px", fontSize: "14px" }}>
              Your configuration is frozen for this run. The Python orbital
              model and ns-3 engine produce every metric.
            </p>
            <label className="field-label" style={{ marginBottom: "14px" }}>
              <span>Mission name</span>
              <input
                autoFocus
                aria-label="Mission name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="field-label" style={{ marginBottom: "14px" }}>
              <span>Routing policy</span>
              <select
                className="sel"
                aria-label="Routing policy"
                value={policy}
                onChange={(e) => setPolicy(e.target.value)}
              >
                {policies
                  .filter((p) => p.available)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
              </select>
            </label>
            {policies.find((p) => p.id === policy)?.checkpoint_required && (
              <label className="field-label" style={{ marginBottom: "14px" }}>
                <span>Checkpoint manifest ID</span>
                <input
                  aria-label="Checkpoint manifest ID"
                  value={checkpoint}
                  onChange={(e) => setCheckpoint(e.target.value)}
                  placeholder="Select a compatible registered checkpoint"
                />
                <small style={{ color: "var(--mute)", fontSize: "11px", marginTop: "2px" }}>
                  Observation/action compatibility is validated by the policy
                  backend.
                </small>
              </label>
            )}
            <div className="launch-summary">
              <span className="launch-chip">
                <Satellite size={14} style={{ color: "var(--acc)" }} />
                <b>{(draft?.constellation?.n_planes ?? run.scenario.constellation?.n_planes ?? 10) *
                  (draft?.constellation?.sats_per_plane ?? run.scenario.constellation?.sats_per_plane ?? 20)}</b> satellites
              </span>
              <span className="launch-chip">
                <Clock3 size={14} style={{ color: "var(--acc)" }} />
                <b>{(draft?.duration_s ?? run.duration_s).toFixed(1)}s</b> simulated
              </span>
              <span className="launch-chip">
                <MapPin size={14} style={{ color: "var(--acc)" }} />
                <b>{(draft?.ground_stations?.length ?? run.scenario.ground_stations?.length ?? 4)}</b> stations
              </span>
            </div>
            {!online && (
              <div className="warning-note">
                <TriangleAlert size={16} style={{ flexShrink: 0, marginTop: "2px" }} />
                <span>
                  The local API is offline. Start the app with Docker Compose to
                  launch simulations. The bundled recorded replay remains
                  available.
                </span>
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "18px" }}>
              <button
                className="btn pri full"
                style={{ justifyContent: "center", padding: "12px 18px", fontWeight: 600, fontSize: "14px" }}
                disabled={
                  busy ||
                  !online ||
                  !cap?.engine_available ||
                  Boolean(
                    policies.find((p) => p.id === policy)?.checkpoint_required &&
                    !checkpoint.trim(),
                  )
                }
                onClick={launch}
              >
                {busy ? (
                  <RefreshCw size={16} className="spin" />
                ) : (
                  <Play size={16} />
                )}
                Launch simulation
                <ArrowRight size={16} />
              </button>
              <button
                className="btn full"
                style={{ justifyContent: "center", fontSize: "13px", color: "var(--mute)" }}
                onClick={() => {
                  setLaunchOpen(false);
                  setView("studio");
                }}
              >
                Review constellation setup
                <ArrowUpRight size={13} />
              </button>
            </div>
          </div>
        </div>
      )}
      {busy && !launchOpen && view !== "studio" && (
        <div className="background-work">
          <RefreshCw size={13} className="spin" />
          Preparing authoritative data…
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <Info size={16} />
          <span>{toast}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {/* ── Mentor demo walkthrough overlay ──────────────────────── */}
      {demoStep !== null && (() => {
        const stage = DEMO_STAGES[demoStep];
        return (
          <div className="demo-walkthrough" role="complementary" aria-label="Mentor demo guide">
            <div className="demo-header">
              <Presentation size={14} />
              <span className="demo-cue-label">{stage.label}</span>
              <button
                className="icon-button demo-close"
                aria-label="Close walkthrough"
                onClick={() => setDemoStep(null)}
              >
                <X size={13} />
              </button>
            </div>
            <div className="demo-cue">{stage.cue}</div>
            <h3 className="demo-heading">{stage.heading}</h3>
            <p className="demo-body">{stage.body}</p>
            <div className="demo-actions">
              <button
                className="primary-button demo-action-btn"
                onClick={() => runDemoStage(stage)}
              >
                {stage.actionLabel}
                <ArrowRight size={13} />
              </button>
            </div>
            <div className="demo-nav">
              <button
                className="secondary-button demo-prev"
                disabled={demoStep === 0}
                onClick={() => setDemoStep((s) => Math.max(0, (s ?? 0) - 1))}
              >
                ← Prev
              </button>
              <span className="demo-pip-row">
                {DEMO_STAGES.map((_, i) => (
                  <button
                    key={i}
                    className={`demo-pip ${i === demoStep ? "active" : ""}`}
                    aria-label={`Stage ${i + 1}`}
                    onClick={() => setDemoStep(i)}
                  />
                ))}
              </span>
              <button
                className="secondary-button demo-next"
                disabled={demoStep === DEMO_STAGES.length - 1}
                onClick={() =>
                  setDemoStep((s) =>
                    Math.min(DEMO_STAGES.length - 1, (s ?? 0) + 1),
                  )
                }
              >
                Next →
              </button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
export default App;
