import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Bot,
  BookmarkPlus,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Crosshair,
  Expand,
  FolderClock,
  GitCompareArrows,
  Info,
  Layers3,
  Map,
  MapPin,
  Maximize2,
  Orbit,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  Satellite,
  Settings2,
  ShieldCheck,
  SkipBack,
  Square,
  TriangleAlert,
  Waypoints,
  X,
  Zap,
  Presentation,
  Link2,
  AlertTriangle,
} from "lucide-react";
import type {
  Capabilities,
  ClassName,
  LiveSnapshot,
  Replay,
  RunRecord,
  Scenario,
  View,
} from "./lib/types";
import { api, download } from "./lib/api";
import {
  CLASS_COLORS,
  flowTimingError,
  format,
  frameAt,
  scenarioDiff,
  utcClock,
  queuePeak,
} from "./lib/model";
import { Studio, ScenarioBadge } from "./components/Studio";
import { Library } from "./components/Library";
import { Sparkline, Trend, DeadlineTracker, QueueBreakdown, RouteChurnCounter } from "./components/Charts";
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
    [speed, setSpeed] = useState(0.25),
    [selected, setSelected] = useState<number | null>(null),
    [flow, setFlow] = useState(1),
    [links, setLinks] = useState(true),
    [orbits, setOrbits] = useState(true),
    [rotate, setRotate] = useState(true),
    [flat, setFlat] = useState(false),
    [focusPath, setFocusPath] = useState(false),
    [reset, setReset] = useState(0),
    [presentation, setPresentation] = useState(false),
    [placing, setPlacing] = useState(false),
    [theme, setTheme] = useState<"light" | "dark">(() => {
      try {
        return (localStorage.getItem("apogee-theme") as "light" | "dark") || "light";
      } catch {
        return "light";
      }
    });
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
    [compareClock, setCompareClock] = useState<"absolute" | "relative">(
      "relative",
    ),
    [sidebar, setSidebar] = useState(false),
    [inspector, setInspector] = useState<"telemetry" | "selection">(
      "telemetry",
    ),
    [bootError, setBootError] = useState(""),
    [baseline, setBaseline] = useState<Replay>(),
    [demoStep, setDemoStep] = useState<number | null>(null);
  const [bookmarks, setBookmarks] = useState<
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
        setSidebar(false);
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
        setSidebar(false);
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
      setSidebar(false);
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
  async function command(c: string) {
    if (!live) return;
    try {
      const record = await api.command(live.id, c);
      setLive(record);
      notify(
        c === "cancel"
          ? "Cancellation requested."
          : `${c === "pause" ? "Pause" : "Resume"} requested; waiting for the engine boundary.`,
      );
    } catch (e) {
      notify(String(e));
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
    metrics = current?.metrics,
    activeLive = Boolean(live && !terminal.has(live.status)),
    nodes = run?.nodes ?? [],
    node = selected === null ? undefined : nodes[selected],
    policies = cap?.policies ?? fallbackPolicies;
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
    selectedFlow = current?.routes.find((r) => r.id === flow),
    elapsed = run
      ? utcClock(run.scenario.epoch, (run.scenario.orbital_start_s ?? 0) + time)
      : "00:00:00.000";
  const timelineEvents = [
    ...(run?.events ?? []),
    ...(run ? (bookmarks[run.id] ?? []) : []),
  ].sort((a, b) => a.time_s - b.time_s);
  const status = activeLive
    ? live?.status === "paused"
      ? "ENGINE PAUSED"
      : followLive
        ? "LIVE SIMULATION"
        : "VIEW PAUSED"
    : run?.status === "preview"
      ? "ORBITAL PREVIEW"
      : run?.status === "completed"
        ? "SAVED REPLAY"
        : (run?.status?.toUpperCase() ?? "CONNECTING");
  const comparisonTime =
      comparison && run
        ? compareClock === "relative"
          ? (time / run.duration_s) * comparison.duration_s
          : Math.min(time, comparison.duration_s)
        : 0,
    detailedComparison = useReplayWindow(comparison, comparisonTime, false),
    comparisonFrame = frameAt(detailedComparison, comparisonTime);
  const differences =
    run && comparison ? scenarioDiff(run.scenario, comparison.scenario) : [];

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
  const globe = (
    <Suspense
      fallback={
        <div className="globe-loading">
          <Orbit size={35} className="spin" />
          <span>Rendering the Earth</span>
        </div>
      }
    >
      <Globe
        run={detailedRun ?? run}
        time={time}
        selected={selected}
        onSelect={(id) => {
          setSelected(id);
          setInspector("selection");
        }}
        flow={flow}
        links={links}
        orbits={orbits}
        rotate={
          rotate && !matchMedia("(prefers-reduced-motion: reduce)").matches
        }
        presentation={presentation}
        placeStation={placing ? place : undefined}
        flat={flat}
        reset={reset}
        focusPath={focusPath}
      />
    </Suspense>
  );
  return (
    <div className={`app ${theme === "light" ? "light-theme" : ""} ${presentation ? "presentation" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to mission workspace
      </a>
      <header className="topbar">
        <button
          className="brand logo"
          onClick={() => setView("mission")}
          aria-label="Apogee mission home"
        >
          <img src="/assets/mark.svg" alt="" />
          <div>
            APOGEE<small>Orbital network lab</small>
          </div>
        </button>
        <nav className="header-nav" id="nav">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={`nav-pill ${view === t.id ? "on" : ""}`}
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
          <span className="connection-status">
            <i className={`dot ${online ? "connected" : ""}`} />
            {online ? "Local system online" : "Offline replay"}
          </span>
          <span className="epoch-clock t">{elapsed} UTC</span>
          <button
            className="tg"
            title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
            aria-label="Toggle color theme"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
          >
            {theme === "light" ? "☾" : "☀"}
          </button>
          <button
            className="tg"
            title="Presentation mode"
            aria-label="Toggle presentation mode"
            onClick={presentationMode}
          >
            <Expand size={15} />
          </button>
          <span className="user-avatar" title="Ayush Ranjan">A</span>
          <button className="btn pri launch-header" onClick={openLaunch}>
            <Plus size={14} />
            New simulation
          </button>
        </div>
      </header>
      <aside className={`sidebar ${sidebar ? "open" : ""}`}>
        <div className="sidebar-group-label">WORKSPACE</div>
        <nav>
          {tabs.map((t) => (
            <button
              key={t.id}
              aria-label={t.label}
              className={view === t.id ? "active" : ""}
              onClick={() => {
                setView(t.id);
                setSidebar(false);
              }}
              title={t.label}
            >
              <t.icon size={19} />
              <span>{t.label}</span>
              {t.id === "library" && <small>{library.length}</small>}
              {view === t.id && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-mission">
          <span className="eyebrow">CURRENT MISSION</span>
          <span
            className={`status-chip ${activeLive ? "running" : "completed"}`}
          >
            <i />
            {activeLive ? "In progress" : "Recorded simulation"}
          </span>
          <h4>{run.name}</h4>
          <p>
            {nodes.filter((n) => n.kind === "satellite").length} satellites ·{" "}
            {run.scenario.constellation?.n_planes ?? 0} planes
          </p>
          <button onClick={() => setView("mission")}>
            Open mission
            <ArrowUpRight size={13} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <button
            onClick={() => {
              setView("studio");
              setSidebar(false);
            }}
          >
            <Settings2 size={17} />
            Mission settings
          </button>
          <div>
            <ShieldCheck size={14} />
            <span>
              LOCAL & REPRODUCIBLE<small>ns-3.44 · SGP4 · ECEF</small>
            </span>
          </div>
        </div>
      </aside>
      <main id="main" className={`main view-${view}`}>
        <div className="workspace-top">
          <div className="breadcrumbs">
            <button
              className="mobile-menu icon-button"
              onClick={() => setSidebar((v) => !v)}
              aria-label="Open navigation"
            >
              <Layers3 size={17} />
            </button>
            <span>WORKSPACE</span>
            <ChevronRight size={11} />
            <b>{tabs.find((t) => t.id === view)?.label}</b>
          </div>
          <span className="system-note">
            <span className="tiny-dot" />
            Science in every orbit.
          </span>
        </div>
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
          <section className="workspace-panel policy-page">
            <div className="page-heading">
              <div>
                <span className="eyebrow">THE INTELLIGENCE LAYER</span>
                <h1>One network. Different decisions.</h1>
                <p>
                  Inspect the implemented routing policies. Future learned
                  controllers use the same capability contract.
                </p>
              </div>
              <span className="outline-badge">6 ENGINEERED BASELINES</span>
            </div>
            <div className="policies-grid">
              {policies.map((p, i) => (
                <button
                  key={p.id}
                  className={`policy-card ${policy === p.id ? "selected" : ""}`}
                  onClick={() => {
                    setPolicy(p.id);
                    notify(`${p.label} selected for the next simulation`);
                  }}
                >
                  <span className="policy-card-number">0{i + 1}</span>
                  <Waypoints size={27} />
                  <h3>{p.label}</h3>
                  <p>
                    {(
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
                    )[p.id] ??
                      "Checkpoint-backed policy. Validate observation and action compatibility before launch."}
                  </p>
                  <span>
                    {policy === p.id ? (
                      <>
                        <Check size={13} />
                        Selected
                      </>
                    ) : (
                      <>
                        {p.kind === "learned"
                          ? "Learned policy"
                          : "Heuristic policy"}
                        <ArrowUpRight size={14} />
                      </>
                    )}
                  </span>
                </button>
              ))}
            </div>
            <div className="future-panel">
              <div className="future-icon">
                <Bot size={28} />
              </div>
              <div>
                <span className="eyebrow">PHASE 5 · PLANNED</span>
                <h2>A place for learned intelligence.</h2>
                <p>
                  PPO training and checkpoint inference are deferred until
                  dashboard acceptance. The policy registry reserves versioned
                  observations, actions and checkpoint compatibility; no trained
                  model is active.
                </p>
              </div>
              <span className="outline-badge">
                COMING AFTER DASHBOARD ACCEPTANCE
              </span>
            </div>
          </section>
        ) : (
          <>
            <div className="mission-heading">
              <div>
                <div className="mission-kicker">
                  <span className="eyebrow">
                    {view === "studio"
                      ? "DESIGN YOUR NETWORK"
                      : view === "compare"
                        ? "EVIDENCE, SIDE BY SIDE"
                        : "A CONNECTED WORLD. A CLEARER VIEW."}
                  </span>
                  <span className={`mode-badge ${activeLive ? "live" : ""}`}>
                    <i />
                    {status}
                  </span>
                </div>
                <h1>
                  {view === "studio"
                    ? "Constellation studio"
                    : view === "compare"
                      ? "Compare missions"
                      : "Mission control"}
                  <span className="heading-period">.</span>
                </h1>
                <p>
                  {view === "studio"
                    ? "Shape an orbital network, then see it come to life."
                    : view === "compare"
                      ? "Compare the conditions before comparing the outcomes."
                      : run.name}{" "}
                  {view === "mission" && (
                    <>
                      <span className="text-divider">/</span>
                      {policies.find((p) => p.id === run.policy)?.label ??
                        run.policy?.replaceAll("_", " ")}
                    </>
                  )}
                </p>
              </div>
              <div className="mission-heading-right">
                {view === "mission" && (
                  <>
                    <div>
                      <span className="eyebrow">SIMULATION TIME</span>
                      <strong>
                        {time.toFixed(2)}
                        <small> / {run.duration_s.toFixed(1)} s</small>
                      </strong>
                    </div>
                    {activeLive && (
                      <div className="wall-time">
                        <span className="eyebrow">ELAPSED WALL TIME</span>
                        <strong>
                          {(live?.wall_seconds ?? 0).toFixed(1)}
                          <small> s · {live?.status}</small>
                        </strong>
                      </div>
                    )}
                    <button
                      className="secondary-button"
                      onClick={() =>
                        run.id.startsWith("demo-") || run.status === "preview"
                          ? download(run, `apogee-${run.id.slice(0, 10)}.json`)
                          : (() => {
                              const a = document.createElement("a");
                              a.href = `/api/v1/runs/${run.id}/export`;
                              a.download = "";
                              a.click();
                            })()
                      }
                    >
                      <ArrowDownToLine size={14} />
                      Export run
                    </button>
                  </>
                )}
                {view === "studio" && (
                  <button className="primary-button" onClick={openLaunch}>
                    <Play size={14} />
                    Launch simulation
                  </button>
                )}
              </div>
            </div>
            {view === "compare" && (
              <div className="comparison-picker">
                <label>
                  MISSION A
                  <select
                    value={run.id}
                    onChange={(e) => {
                      const id = e.target.value;
                      openRun(id).then(() => setView("compare"));
                      if (compared.length !== 2)
                        setCompared([
                          id,
                          library.find((r) => r.id !== id)?.id ?? id,
                        ]);
                    }}
                  >
                    {library.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </label>
                <GitCompareArrows size={18} />
                <label>
                  MISSION B
                  <select
                    value={comparison?.id ?? ""}
                    onChange={(e) => {
                      setCompared([run.id, e.target.value]);
                      loadReplay(e.target.value)
                        .then(setComparison)
                        .catch((e) => notify(String(e)));
                    }}
                  >
                    <option value="" disabled>
                      Choose a recorded mission
                    </option>
                    {library
                      .filter((r) => r.id !== run.id)
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  ALIGNMENT
                  <select
                    value={compareClock}
                    onChange={(e) =>
                      setCompareClock(e.target.value as "relative" | "absolute")
                    }
                  >
                    <option value="relative">Relative episode time</option>
                    <option value="absolute">Simulation seconds</option>
                  </select>
                </label>
                {comparison && (
                  <span
                    className={`match-badge ${differences.length ? "warning" : ""}`}
                  >
                    {differences.length ? (
                      <>
                        <TriangleAlert size={14} />
                        Different conditions
                      </>
                    ) : (
                      <>
                        <ShieldCheck size={14} />
                        Matched scenario
                      </>
                    )}
                  </span>
                )}
              </div>
            )}
            <div
              className={`mission-layout ${view === "studio" ? "with-studio" : ""} ${view === "compare" && comparison ? "with-comparison" : ""}`}
            >
              {view === "studio" && (
                <div className="studio-panel">
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
                      setName(
                        "Aurora · " +
                          (presets.find(
                            (p) =>
                              JSON.stringify(p.scenario) === JSON.stringify(c),
                          )?.name ?? "Custom mission"),
                      );
                    }}
                    onPreview={generatePreview}
                    onSave={saveDesign}
                    busy={busy}
                    onPlace={() => setPlacing((v) => !v)}
                    placing={placing}
                  />
                </div>
              )}
              <section
                className="globe-panel"
                aria-label="Orbital network visualization"
              >
                <div className="globe-topline">
                  <span>
                    <i className="status-dot" />
                    {run.status === "preview"
                      ? "ORBITAL DESIGN PREVIEW"
                      : "ORBITAL NETWORK"}
                    <small>
                      {run.frame} · {run.units}
                    </small>
                  </span>
                  <div className="globe-tools">
                    <button
                      className={`icon-button ${flat ? "selected" : ""}`}
                      title="Toggle 2D map"
                      aria-label="Toggle 2D map"
                      onClick={() => setFlat((v) => !v)}
                    >
                      <Map size={14} />
                    </button>
                    <button
                      className={`icon-button ${rotate ? "selected" : ""}`}
                      title="Auto-orbit camera"
                      aria-label="Toggle camera rotation"
                      onClick={() => setRotate((v) => !v)}
                    >
                      <RotateCcw size={14} />
                    </button>
                    <button
                      className="icon-button"
                      title="Reset camera"
                      aria-label="Reset camera"
                      onClick={() => setReset((v) => v + 1)}
                    >
                      <Crosshair size={15} />
                    </button>
                    <button
                      className={`icon-button ${focusPath ? "selected" : ""}`}
                      title="Show active path only"
                      aria-label="Toggle active path focus"
                      onClick={() => setFocusPath((v) => !v)}
                    >
                      <Waypoints size={14} />
                    </button>
                    <button
                      className="icon-button"
                      title="Presentation mode"
                      aria-label="Presentation mode"
                      onClick={presentationMode}
                    >
                      <Maximize2 size={14} />
                    </button>
                    <button
                      className={`icon-button ${demoStep !== null ? "selected" : ""}`}
                      title="Mentor demo walkthrough"
                      aria-label="Start mentor demo"
                      onClick={() => setDemoStep(demoStep !== null ? null : 0)}
                    >
                      <Presentation size={14} />
                    </button>
                  </div>
                </div>
                <div className="globe-canvas">{globe}</div>
                <div className="globe-coordinate">
                  <span className="coordinate-line" />
                  <span>
                    EARTH / LOW ORBIT
                    <small>
                      {run.scenario.constellation
                        ? `${run.scenario.constellation.altitude_km} KM ABOVE THE SURFACE`
                        : "HISTORICAL GRAPH · ORBIT GEOMETRY UNAVAILABLE"}
                    </small>
                  </span>
                  <span className={`data-source-badge ${activeLive ? "live" : run.bundled ? "demo" : ""}`}>
                    {activeLive ? "LIVE SIMULATION" : run.bundled ? "RECORDED DEMO" : "SAVED REPLAY"}
                  </span>
                </div>
                <div className="globe-stats">
                  <div>
                    <Satellite size={15} />
                    <strong>
                      {nodes.filter((n) => n.kind === "satellite").length}
                    </strong>
                    <span>satellites</span>
                  </div>
                  <div>
                    <Waypoints size={15} />
                    <strong>{current.links.length}</strong>
                    <span>active links</span>
                  </div>
                  <div>
                    <MapPin size={15} />
                    <strong>
                      {nodes.filter((n) => n.kind === "ground").length}
                    </strong>
                    <span>stations</span>
                  </div>
                </div>
                <div className="globe-layer-controls">
                  <button
                    className={links ? "active" : ""}
                    onClick={() => setLinks((v) => !v)}
                  >
                    <span className="legend-line" />
                    Network links
                  </button>
                  <button
                    className={orbits ? "active" : ""}
                    onClick={() => setOrbits((v) => !v)}
                  >
                    <span className="legend-line dashed" />
                    Orbit traces
                  </button>
                  <span className="globe-hint">
                    {placing
                      ? "DOUBLE-CLICK EARTH TO PLACE A STATION"
                      : "DRAG TO ORBIT · SCROLL TO ZOOM · SELECT A NODE"}
                  </span>
                </div>
              </section>
              {view === "compare" && comparison ? (
                <section className="compare-inspector">
                  <div className="section-heading">
                    <h3>Outcome comparison</h3>
                    <span>AT CURSOR</span>
                  </div>
                  <div className="comparison-names">
                    <span>{run.name}</span>
                    <span>{comparison.name}</span>
                  </div>
                  {[
                    [
                      "Delivery",
                      format.percent(metrics?.delivery_ratio),
                      format.percent(comparisonFrame?.metrics?.delivery_ratio),
                    ],
                    [
                      "Delivered packets",
                      format.number(metrics?.delivered),
                      format.number(comparisonFrame?.metrics?.delivered),
                    ],
                    [
                      "Dropped packets",
                      format.number(metrics?.dropped),
                      format.number(comparisonFrame?.metrics?.dropped),
                    ],
                    [
                      "Latency p95",
                      `${format.ms(metrics?.delay_p95_s)} ms`,
                      `${format.ms(comparisonFrame?.metrics?.delay_p95_s)} ms`,
                    ],
                    [
                      "Goodput",
                      `${format.mbps(metrics?.goodput_bps)} Mbps`,
                      `${format.mbps(comparisonFrame?.metrics?.goodput_bps)} Mbps`,
                    ],
                  ].map(([label, a, b]) => (
                    <div className="comparison-metric" key={label}>
                      <span>{label}</span>
                      <strong>{a}</strong>
                      <strong>{b}</strong>
                    </div>
                  ))}
                  <div className="comparison-class-heading">
                    DEADLINE SUCCESS
                  </div>
                  {(["CONTROL", "REALTIME"] as ClassName[]).map((c) => (
                    <div className="comparison-metric" key={c}>
                      <span>
                        <i className={`class-dot ${c.toLowerCase()}`} />
                        {c}
                      </span>
                      <strong>
                        {format.percent(metrics?.classes[c].deadline_success)}
                      </strong>
                      <strong>
                        {format.percent(
                          comparisonFrame?.metrics?.classes[c].deadline_success,
                        )}
                      </strong>
                    </div>
                  ))}
                  <div className="comparison-class-heading">
                    FULL EPISODE · FINAL SUMMARIES
                  </div>
                  {[
                    [
                      "Bulk active-goodput fairness",
                      run.summary?.bulk_jain_active_goodput?.toFixed(3) ?? "—",
                      comparison.summary?.bulk_jain_active_goodput?.toFixed(
                        3,
                      ) ?? "—",
                    ],
                    [
                      "Max backlogged Bulk gap",
                      `${format.ms(run.summary?.bulk_service?.max_backlogged_service_gap_s)} ms`,
                      `${format.ms(comparison.summary?.bulk_service?.max_backlogged_service_gap_s)} ms`,
                    ],
                  ].map(([label, a, b]) => (
                    <div className="comparison-metric" key={label}>
                      <span>{label}</span>
                      <strong>{a}</strong>
                      <strong>{b}</strong>
                    </div>
                  ))}
                  {differences.length > 0 && (
                    <div className="warning-note">
                      <TriangleAlert size={15} />
                      <span>
                        These runs differ in {differences.join(", ")}. Their
                        difference does not isolate the effect of routing
                        policy.
                      </span>
                    </div>
                  )}
                  <button
                    className="secondary-button full"
                    onClick={() => {
                      const next = comparison;
                      setComparison(run);
                      setRun(next);
                      setTime(comparisonTime);
                    }}
                  >
                    <GitCompareArrows size={14} />
                    Inspect mission B on globe
                  </button>
                </section>
              ) : (
                view !== "studio" && (
                  <aside className="telemetry-panel">
                    <div className="inspector-tabs">
                      <button
                        className={inspector === "telemetry" ? "active" : ""}
                        onClick={() => setInspector("telemetry")}
                      >
                        Telemetry
                      </button>
                      <button
                        className={inspector === "selection" ? "active" : ""}
                        onClick={() => setInspector("selection")}
                      >
                        Inspector{node && <i />}
                      </button>
                      <span className="pulse-dot" />
                    </div>
                    {inspector === "selection" ? (
                      <>
                        <div className="inspector-object">
                          <span className="object-icon">
                            {node?.kind === "ground" ? (
                              <MapPin size={24} />
                            ) : (
                              <Satellite size={24} />
                            )}
                          </span>
                          <span className="eyebrow">
                            {node?.kind === "ground"
                              ? "GROUND STATION"
                              : "SELECTED OBJECT"}
                          </span>
                          <h2>{node?.name ?? "Explore the network"}</h2>
                          <p>
                            {node
                              ? "Physical position at the current timeline cursor."
                              : "Select a satellite or ground station on the globe."}
                          </p>
                        </div>
                        {node && (
                          <>
                            <div className="detail-line">
                              <span>Connected links</span>
                              <b>
                                {
                                  current.links.filter(
                                    (l) => l.a === node.id || l.b === node.id,
                                  ).length
                                }
                              </b>
                            </div>
                            {/* Link lifetime badges — one row per active link */}
                            {current.links
                              .filter(
                                (l) => l.a === node.id || l.b === node.id,
                              )
                              .slice(0, 6)
                              .map((l) => {
                                const peer =
                                  nodes[l.a === node.id ? l.b : l.a];
                                // Check if this link is present in the next frame (look-ahead)
                                const nextFrame = run.frames.find(
                                  (f) => f.time_s > time,
                                );
                                const stillUp = nextFrame
                                  ? nextFrame.links.some(
                                      (nl) =>
                                        (nl.a === l.a && nl.b === l.b) ||
                                        (nl.a === l.b && nl.b === l.a),
                                    )
                                  : true;
                                const delayMs = (l.delay_s * 1000).toFixed(1);
                                // Warn if delay > 40 ms (approaching link budget) or link drops next frame
                                const warn =
                                  !stillUp || l.delay_s > 0.04;
                                return (
                                  <div
                                    key={l.id}
                                    className={`link-lifetime-badge${warn ? " warning" : ""}`}
                                    title={
                                      !stillUp
                                        ? "Link drops in the next snapshot"
                                        : `Propagation delay ${delayMs} ms`
                                    }
                                  >
                                    {warn ? (
                                      <AlertTriangle size={10} />
                                    ) : (
                                      <Link2 size={10} />
                                    )}
                                    <span>
                                      {peer?.name ?? `node-${l.a === node.id ? l.b : l.a}`}
                                    </span>
                                    <small>{delayMs} ms</small>
                                    {!stillUp && (
                                      <small className="link-drop-label">
                                        dropping
                                      </small>
                                    )}
                                  </div>
                                );
                              })}
                            {["X · ECEF", "Y · ECEF", "Z · ECEF"].map(
                              (label, i) => (
                                <div className="detail-line" key={label}>
                                  <span>{label}</span>
                                  <b>
                                    {current.positions[node.id]?.[i].toFixed(
                                      2,
                                    ) ?? "—"}
                                    <small> km</small>
                                  </b>
                                </div>
                              ),
                            )}
                            {node.coordinates && (
                              <div className="detail-line">
                                <span>Geographic position</span>
                                <b>
                                  {node.coordinates[0].toFixed(3)}°,{" "}
                                  {node.coordinates[1].toFixed(3)}°
                                </b>
                              </div>
                            )}
                          </>
                        )}
                        <div className="section-heading">
                          <h3>Route focus</h3>
                        </div>
                        <select
                          className="route-select"
                          aria-label="Highlighted traffic flow"
                          value={flow}
                          onChange={(e) => setFlow(Number(e.target.value))}
                        >
                          {run.scenario.flows.map((f) => (
                            <option value={f.flow_id} key={f.flow_id}>
                              Flow {f.flow_id} · {f.flow_type}
                            </option>
                          ))}
                        </select>
                        <div className="route-chain">
                          {selectedFlow?.path.length ? (
                            selectedFlow.path.map((id, i) => (
                              <button
                                key={`${i}-${id}`}
                                onClick={() => setSelected(id)}
                              >
                                <span
                                  className={
                                    i === 0 ||
                                    i === selectedFlow.path.length - 1
                                      ? "endpoint"
                                      : ""
                                  }
                                />
                                {nodes[id]?.name}
                                {i < selectedFlow.path.length - 1 && (
                                  <ChevronDown size={10} />
                                )}
                              </button>
                            ))
                          ) : (
                            <p>No route recorded at this time.</p>
                          )}
                        </div>
                        {current.forecast?.find((f) => f.flow_id === flow) && (
                          <div className="controller-estimate">
                            <div className="section-heading">
                              <h3>Controller estimate</h3>
                            </div>
                            <div className="detail-line">
                              <span>Estimated path delay</span>
                              <b>
                                {format.ms(
                                  current.forecast.find(
                                    (f) => f.flow_id === flow,
                                  )?.estimated_delay_s,
                                )}{" "}
                                ms
                              </b>
                            </div>
                            <div className="detail-line">
                              <span>Deadline at risk</span>
                              <b>
                                {current.forecast.find(
                                  (f) => f.flow_id === flow,
                                )?.deadline_at_risk
                                  ? "Yes"
                                  : "No"}
                              </b>
                            </div>
                            <div className="detail-line">
                              <span>Heuristic fallback</span>
                              <b>
                                {current.forecast.find(
                                  (f) => f.flow_id === flow,
                                )?.fallback
                                  ? "Applied"
                                  : "Not applied"}
                              </b>
                            </div>
                          </div>
                        )}
                        <div className="info-note">
                          Highlighted lines are the installed class route. They
                          do not animate or invent individual packet deliveries.
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="telemetry-heading">
                          <span className="eyebrow">NETWORK VITALS</span>
                          <span className="live-time">
                            t + {time.toFixed(2)} s
                          </span>
                        </div>
                        <div className="main-metric">
                          <span>
                            Packet delivery
                            <span title="Delivered / generated UDP datagrams at the current cursor">
                              <Info size={12} />
                            </span>
                          </span>
                          <div>
                            <strong>
                              {format.percent(metrics?.delivery_ratio)}
                            </strong>
                            <Sparkline
                              values={run.frames
                                .slice(
                                  0,
                                  Math.max(
                                    2,
                                    run.frames.filter((f) => f.time_s <= time)
                                      .length,
                                  ),
                                )
                                .map(
                                  (f) => (f.metrics?.delivery_ratio ?? 0) * 100,
                                )}
                            />
                          </div>
                          <small>
                            {metrics
                              ? `${format.number(metrics.delivered)} delivered of ${format.number(metrics.generated)} generated`
                              : "Unavailable in geometry preview"}
                          </small>
                        </div>
                        <div className="metric-pair">
                          <div>
                            <span>Latency p95</span>
                            <strong>
                              {format.ms(metrics?.delay_p95_s)}
                              <small>ms</small>
                            </strong>
                          </div>
                          <div>
                            <span>Goodput</span>
                            <strong>
                              {format.mbps(metrics?.goodput_bps)}
                              <small>Mbps</small>
                            </strong>
                          </div>
                        </div>
                        <div className="packet-accounting">
                          <span>
                            <i className="mint-dot" />
                            {format.number(metrics?.delivered)}
                            <small>delivered</small>
                          </span>
                          <span>
                            <i className="amber-dot" />
                            {format.number(metrics?.dropped)}
                            <small>dropped</small>
                          </span>
                          <span>
                            <i className="blue-dot" />
                            {format.number(metrics?.in_flight)}
                            <small>in flight</small>
                          </span>
                        </div>
                        <div className="section-heading service-heading">
                          <h3>Service classes</h3>
                          <span>AT CURSOR</span>
                        </div>
                        {(["CONTROL", "REALTIME", "BULK"] as ClassName[]).map(
                          (c) => {
                            const m = metrics?.classes[c],
                              ratio =
                                c === "BULK"
                                  ? m && m.generated
                                    ? m.delivered / m.generated
                                    : null
                                  : m?.deadline_success;
                            return (
                              <div className="class-metric" key={c}>
                                <div>
                                  <i
                                    className={`class-dot ${c.toLowerCase()}`}
                                  />
                                  <b>
                                    {c === "REALTIME"
                                      ? "Realtime"
                                      : c === "CONTROL"
                                        ? "Control"
                                        : "Bulk"}
                                  </b>
                                  <span>
                                    {c === "BULK"
                                      ? "delivery"
                                      : "deadline success"}
                                  </span>
                                  <strong>{format.percent(ratio)}</strong>
                                </div>
                                <div className="class-track">
                                  <span
                                    style={{
                                      width: `${Math.min(100, Math.max(0, (ratio ?? 0) * 100))}%`,
                                      background: CLASS_COLORS[c],
                                    }}
                                  />
                                </div>
                                <small>
                                  {c === "BULK"
                                    ? `${format.mbps(m?.goodput_bps)} Mbps · run window`
                                    : `${Number((run.scenario.qos.targets as Record<string, { deadline_s?: number }> | undefined)?.[c]?.deadline_s ?? (c === "CONTROL" ? 0.05 : 0.1)) * 1000} ms class target · flow overrides retained`}
                                </small>
                              </div>
                            );
                          },
                        )}
                        <div className="queue-strip">
                          <span>
                            Peak directional queue{" "}
                            <b>
                              {format.number(queuePeak(current))}
                              <small> packets</small>
                            </b>
                          </span>
                          <span>
                            Queued wire bytes{" "}
                            <b>
                              {current.queues.length &&
                              current.queues.every((q) => q.bytes != null)
                                ? format.number(
                                    current.queues.reduce(
                                      (n, q) => n + q.bytes!,
                                      0,
                                    ),
                                  )
                                : "—"}
                            </b>
                          </span>
                        </div>
                        <div className="telemetry-note">
                          <ShieldCheck size={13} />
                          <span>
                            {activeLive
                              ? "Provisional, cumulative outcomes"
                              : "Recorded outcomes at the timeline cursor"}
                            . Latency uses delivered packets.
                          </span>
                        </div>
                        <div className="section-heading service-heading">
                          <h3>Deadline success</h3>
                          <span>AT CURSOR</span>
                        </div>
                        <DeadlineTracker metrics={metrics ?? null} scenario={run.scenario} />
                        <QueueBreakdown queues={current.queues} links={current.links} />
                        <RouteChurnCounter events={run.events} />
                      </>
                    )}
                  </aside>
                )
              )}
            </div>
            {view === "compare" && !comparison && (
              <div className="comparison-empty">
                <GitCompareArrows size={23} />
                <span>
                  Select a second mission above, or choose two runs from the
                  library.
                </span>
                <button
                  className="text-button"
                  onClick={() => setView("library")}
                >
                  Open library
                  <ArrowUpRight size={13} />
                </button>
              </div>
            )}
            <div className="timeline-panel">
              <div className="playback-controls">
                <button
                  className="icon-button"
                  aria-label="Return to start"
                  disabled={activeLive}
                  onClick={() => {
                    setTime(0);
                    setPlaying(false);
                    setFollowLive(false);
                  }}
                >
                  <SkipBack size={16} />
                </button>
                <button
                  className="playback-main"
                  aria-label={
                    activeLive
                      ? followLive
                        ? "Pause view"
                        : "Catch up to live"
                      : playing
                        ? "Pause playback"
                        : "Play playback"
                  }
                  onClick={() => {
                    if (activeLive) {
                      setFollowLive((v) => !v);
                    } else {
                      if (time >= run.duration_s) setTime(0);
                      setPlaying((v) => !v);
                    }
                  }}
                >
                  {activeLive ? (
                    followLive ? (
                      <Pause size={15} />
                    ) : (
                      <Play size={15} />
                    )
                  ) : playing ? (
                    <Pause size={15} />
                  ) : (
                    <Play size={15} />
                  )}
                </button>
                <button
                  className="icon-button"
                  aria-label="Bookmark current time"
                  title="Bookmark current time"
                  disabled={activeLive || run.status === "preview"}
                  onClick={() => {
                    setBookmarks((previous) => ({
                      ...previous,
                      [run.id]: [
                        ...(previous[run.id] ?? []),
                        {
                          time_s: time,
                          kind: "bookmark",
                          title: "Saved bookmark",
                          detail: `${run.name} at ${time.toFixed(2)} seconds`,
                        },
                      ],
                    }));
                    notify("Bookmark saved in this browser.");
                  }}
                >
                  <BookmarkPlus size={15} />
                </button>
                <select
                  aria-label="Playback speed"
                  value={speed}
                  onChange={(e) => setSpeed(Number(e.target.value))}
                  disabled={activeLive && followLive}
                >
                  {[0.1, 0.25, 0.5, 1, 2, 4].map((s) => (
                    <option key={s} value={s}>
                      {s}×
                    </option>
                  ))}
                </select>
              </div>
              <div className="timeline-track">
                <div className="timeline-labels">
                  <span>
                    {activeLive ? "SIMULATION PROGRESS" : "MISSION TIMELINE"}
                  </span>
                  <div>
                    <i className="event-marker" />
                    Topology events
                    <span>
                      {time.toFixed(2)} / {run.duration_s.toFixed(2)} s
                    </span>
                  </div>
                </div>
                <div className="range-wrap">
                  <input
                    aria-label="Simulation timeline"
                    type="range"
                    min={0}
                    max={run.duration_s}
                    step={0.01}
                    value={Math.min(time, run.duration_s)}
                    disabled={activeLive}
                    onChange={(e) => {
                      setTime(Number(e.target.value));
                      setPlaying(false);
                    }}
                    style={
                      {
                        "--progress": `${(time / run.duration_s) * 100}%`,
                      } as React.CSSProperties
                    }
                  />
                  {timelineEvents.map((e, i) => (
                    <button
                      className="timeline-event"
                      key={`${e.time_s}-${i}`}
                      style={{ left: `${(e.time_s / run.duration_s) * 100}%` }}
                      title={`${e.title} · ${e.time_s.toFixed(2)} s`}
                      aria-label={`Jump to ${e.title} at ${e.time_s.toFixed(2)} seconds`}
                      onClick={() => {
                        if (!activeLive) {
                          setTime(e.time_s);
                          setPlaying(false);
                          notify(`${e.title}: ${e.detail}`);
                        }
                      }}
                    />
                  ))}
                </div>
                <div className="timeline-ticks">
                  {[0, 0.25, 0.5, 0.75, 1].map((p) => (
                    <span key={p}>{(run.duration_s * p).toFixed(1)}s</span>
                  ))}
                </div>
              </div>
              <div className="timeline-source">
                <span className={`mode-badge ${activeLive ? "live" : ""}`}>
                  <i />
                  {activeLive
                    ? live?.status === "paused"
                      ? "PAUSED"
                      : followLive
                        ? "LIVE"
                        : "VIEW PAUSED"
                    : run.status === "preview"
                      ? "PREVIEW"
                      : "REPLAY"}
                </span>
                {activeLive && (
                  <>
                    <button
                      className="text-button"
                      onClick={() =>
                        command(live?.status === "paused" ? "resume" : "pause")
                      }
                    >
                      {live?.status === "paused"
                        ? "Resume engine"
                        : "Pause engine"}
                    </button>
                    <button
                      className="icon-button danger"
                      aria-label="Cancel simulation"
                      onClick={() => command("cancel")}
                    >
                      <Square size={13} />
                    </button>
                  </>
                )}
              </div>
            </div>
            {view === "mission" && (
              <div className="analytics-row">
                <section className="chart-panel">
                  <div className="chart-title">
                    <div>
                      <span className="eyebrow">DELIVERED DATAGRAMS</span>
                      <h3>
                        Latency over time <small>p95 · cumulative</small>
                      </h3>
                    </div>
                    <Activity size={16} />
                  </div>
                  <Trend
                    frames={run.frames}
                    field="delay"
                    color="#9ee3d5"
                    unit="ms"
                    cursor={time}
                  />
                </section>
                <section className="chart-panel">
                  <div className="chart-title">
                    <div>
                      <span className="eyebrow">APPLICATION DELIVERY</span>
                      <h3>
                        Network goodput <small>run-window average</small>
                      </h3>
                    </div>
                    <Zap size={16} />
                  </div>
                  <Trend
                    frames={run.frames}
                    field="goodput"
                    color="#7aa5e2"
                    unit="Mbps"
                    cursor={time}
                  />
                </section>
                <section className="event-panel">
                  <div className="chart-title">
                    <div>
                      <span className="eyebrow">MISSION LOG</span>
                      <h3>Events & transitions</h3>
                    </div>
                    <Radio size={16} />
                  </div>
                  <div className="event-list">
                    {run.events.length ? (
                      run.events.slice(-4).map((e, i) => (
                        <button
                          key={i}
                          className={e.time_s <= time ? "past" : ""}
                          onClick={() => {
                            if (!activeLive) {
                              setTime(e.time_s);
                              setPlaying(false);
                            }
                          }}
                        >
                          <span>{e.time_s.toFixed(2)}s</span>
                          <i />
                          <span>
                            <b>{e.title}</b>
                            <small>{e.detail}</small>
                          </span>
                          <ChevronRight size={12} />
                        </button>
                      ))
                    ) : (
                      <div className="quiet-event">
                        <Check size={14} />
                        <span>
                          No topology transitions recorded in this view.
                        </span>
                      </div>
                    )}
                  </div>
                </section>
              </div>
            )}
            <footer className="workspace-footer">
              <div>
                <ShieldCheck size={13} />
                <span>{run.source}</span>
              </div>
              <span>
                <ScenarioBadge run={run} />
                <span className="foot-seed">SEED {run.scenario.seed}</span>
              </span>
            </footer>
          </>
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
              className="modal-close icon-button"
              aria-label="Close launch"
              onClick={() => setLaunchOpen(false)}
            >
              <X size={18} />
            </button>
            <span className="modal-symbol">
              <Orbit size={31} />
            </span>
            <span className="eyebrow">A NEW ORBITAL EXPERIMENT</span>
            <h2 id="launch-title">Ready for launch.</h2>
            <p>
              Your configuration is frozen for this run. The Python orbital
              model and ns-3 engine produce every metric.
            </p>
            <label className="field">
              <span>Mission name</span>
              <input
                autoFocus
                aria-label="Mission name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Routing policy</span>
              <select
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
              <label className="field">
                <span>Checkpoint manifest ID</span>
                <input
                  aria-label="Checkpoint manifest ID"
                  value={checkpoint}
                  onChange={(e) => setCheckpoint(e.target.value)}
                  placeholder="Select a compatible registered checkpoint"
                />
                <small>
                  Observation/action compatibility is validated by the policy
                  backend.
                </small>
              </label>
            )}
            <div className="launch-summary">
              <span>
                <Satellite size={15} />
                {draft.constellation.n_planes *
                  draft.constellation.sats_per_plane}{" "}
                satellites
              </span>
              <span>
                <Clock3 size={15} />
                {draft.duration_s} s simulated
              </span>
              <span>
                <MapPin size={15} />
                {draft.ground_stations.length} stations
              </span>
            </div>
            {!online && (
              <div className="warning-note">
                <TriangleAlert size={16} />
                <span>
                  The local API is offline. Start the app with Docker Compose to
                  launch simulations. The bundled recorded replay remains
                  available.
                </span>
              </div>
            )}
            <button
              className="primary-button full launch-confirm"
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
              className="text-button full"
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
