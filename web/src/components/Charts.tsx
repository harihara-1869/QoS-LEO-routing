import { useId } from "react";
import { TriangleAlert } from "lucide-react";
import { queuePeak } from "../lib/model";
import type {
  ClassName,
  Frame,
  LinkData,
  Metrics,
  RunEvent,
  Scenario,
} from "../lib/types";

export function Trend({
  frames,
  field,
  color,
  unit,
  cursor,
}: {
  frames: Frame[];
  field: "delay" | "goodput" | "queue";
  color: string;
  unit: string;
  cursor: number;
}) {
  const id = useId().replaceAll(":", "");
  const width = 440,
    height = 100,
    pad = 6;
  const points = frames
    .map((f) => ({
      t: f.time_s,
      v:
        field === "delay"
          ? f.metrics?.delay_p95_s == null
            ? null
            : f.metrics.delay_p95_s * 1000
          : field === "goodput"
            ? f.metrics?.goodput_bps == null
              ? null
              : f.metrics.goodput_bps / 1e6
            : queuePeak(f),
    }))
    .filter((p): p is { t: number; v: number } => p.v !== null);
  const max = Math.max(1, ...points.map((p) => p.v)) * 1.1,
    duration = Math.max(0.001, frames.at(-1)?.time_s ?? 1);
  const coords = points.map(
    (p) =>
      `${pad + (p.t / duration) * (width - pad * 2)},${height - pad - (p.v / max) * (height - pad * 2)}`,
  );
  const line = coords.length ? `M${coords.join(" L")}` : "";
  return (
    <div className="trend">
      <div className="chart-scale">
        <span>
          {points.length ? max.toFixed(field === "goodput" ? 1 : 0) : "—"}{" "}
          {unit}
        </span>
        <span>0</span>
      </div>
      {!points.length && (
        <span className="chart-unavailable">No recorded samples</span>
      )}
      <svg
        role="img"
        aria-label={`${field} over simulation time`}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity=".25" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75, 1].map((p) => (
          <line
            key={p}
            x1="0"
            x2={width}
            y1={height * p - 1}
            y2={height * p - 1}
            stroke="#1c2a35"
            strokeDasharray="3 5"
          />
        ))}
        {line && (
          <>
            <path
              d={`${line} L${width - pad},${height} L${pad},${height} Z`}
              fill={`url(#${id})`}
            />
            <path
              d={line}
              fill="none"
              stroke={color}
              strokeWidth="1.8"
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}
        <line
          x1={pad + (cursor / duration) * (width - pad * 2)}
          x2={pad + (cursor / duration) * (width - pad * 2)}
          y1="0"
          y2={height}
          stroke="#d7e5ec"
          opacity=".45"
          strokeDasharray="3 4"
        />
      </svg>
    </div>
  );
}

export function Sparkline({
  values,
  color = "#a8ecd8",
}: {
  values: number[];
  color?: string;
}) {
  if (!values.length)
    return <div className="spark-chart spark-empty">No recorded samples</div>;
  const max = Math.max(1, ...values);
  const precision = max >= 10 ? 0 : 1;
  const guides = [1, 0.75, 0.5, 0.25, 0].map((q) => ({
    q,
    y: 24 - q * 20,
    label: q === 0 ? "0" : (q * max).toFixed(precision),
  }));
  return (
    <div className="spark-chart">
      <svg
        className="sparkline"
        viewBox="0 0 90 26"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {guides.map(({ q, y }) => (
          <line
            key={q}
            x1="0"
            x2="90"
            y1={y}
            y2={y}
            stroke="var(--line)"
            strokeDasharray={q === 0 ? undefined : "2 3"}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <polyline
          points={values
            .map(
              (v, i) =>
                `${(i / Math.max(1, values.length - 1)) * 90},${24 - (v / max) * 20}`,
            )
            .join(" ")}
          stroke={color}
          fill="none"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="spark-guides" aria-hidden="true">
        {guides.map(({ q, y, label }) => (
          <span key={q} style={{ top: `${(y / 26) * 100}%` }}>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── DeadlineTracker ──────────────────────────────────────────────────────────

type QosTargets = Record<string, { deadline_s?: number } | undefined>;

function getRatio(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

function barColor(ratio: number, classColor: string): string {
  if (ratio < 0.5) return "var(--danger, #ef4444)";
  if (ratio < 0.75) return "var(--warn, #f59e0b)";
  return classColor;
}

export function DeadlineTracker({
  metrics,
  scenario,
}: {
  metrics: Metrics | null;
  scenario: Scenario;
}) {
  const targets = (scenario.qos as { targets?: QosTargets } | undefined)
    ?.targets;
  const flowDeadline = (className: ClassName) =>
    scenario.flows.find(
      (flow) => flow.flow_type === className && flow.deadline_s != null,
    )?.deadline_s;

  const controlDeadline =
    targets?.["CONTROL"]?.deadline_s ?? flowDeadline("CONTROL");
  const realtimeDeadline =
    targets?.["REALTIME"]?.deadline_s ?? flowDeadline("REALTIME");

  const controlMetrics = metrics?.classes?.["CONTROL"];
  const realtimeMetrics = metrics?.classes?.["REALTIME"];
  const bulkMetrics = metrics?.classes?.["BULK"];

  const controlRatio = controlMetrics?.deadline_success ?? null;
  const realtimeRatio = realtimeMetrics?.deadline_success ?? null;
  const bulkRatio =
    bulkMetrics != null && bulkMetrics.generated > 0
      ? bulkMetrics.delivered / bulkMetrics.generated
      : null;

  const rows: {
    label: string;
    ratio: number | null;
    classColor: string;
    target?: string;
  }[] = [
    {
      label: "CONTROL",
      ratio: controlRatio,
      classColor: "var(--control-class)",
      target:
        controlDeadline != null
          ? `${(controlDeadline * 1000).toFixed(0)} ms target`
          : undefined,
    },
    {
      label: "REALTIME",
      ratio: realtimeRatio,
      classColor: "var(--realtime-class)",
      target:
        realtimeDeadline != null
          ? `${(realtimeDeadline * 1000).toFixed(0)} ms target`
          : undefined,
    },
    {
      label: "BULK",
      ratio: bulkRatio,
      classColor: "var(--bulk-class)",
    },
  ];

  return (
    <div className="deadline-tracker">
      {rows.map(({ label, ratio, classColor, target }) => {
        const fill = ratio != null ? barColor(ratio, classColor) : classColor;
        const pct = ratio != null ? ratio * 100 : 0;
        return (
          <div key={label}>
            <div className="deadline-bar-wrap">
              <span className="deadline-bar-label">{label}</span>
              <div className="deadline-bar-bg">
                <div
                  className="deadline-bar-fill"
                  style={{ width: `${pct}%`, background: fill }}
                />
              </div>
              <span className="deadline-bar-value">
                {ratio != null ? getRatio(ratio) : "—"}
              </span>
            </div>
            {target && <div className="deadline-target">{target}</div>}
          </div>
        );
      })}
    </div>
  );
}

// ── QueueBreakdown ───────────────────────────────────────────────────────────

export function QueueBreakdown({
  queues,
  links,
}: {
  queues: Frame["queues"] | Record<string, number> | undefined;
  links: LinkData[];
}) {
  const totalPackets = Array.isArray(queues)
    ? queues.reduce((sum, q) => sum + (q.packets ?? 0), 0)
    : typeof queues === "object" && queues !== null
      ? Object.values(queues).reduce((sum, p) => sum + (typeof p === "number" ? p : 0), 0)
      : 0;
  const totalCapacity = links.reduce(
    (sum, link) => sum + (link.queue_packets ?? 0) * 2,
    0,
  );
  const interfaceCount = links.length * 2;
  const pressure = totalCapacity > 0 ? totalPackets / totalCapacity : 0;
  const pct = Math.min(pressure * 100, 100);
  const backlogged = Array.isArray(queues)
    ? queues.filter((q) => (q.packets ?? 0) > 0).length
    : 0;

  return (
    <div style={{ marginTop: "8px" }}>
      {pressure > 0.7 && (
        <div className="congestion-alert" style={{ marginBottom: "8px" }}>
          <TriangleAlert size={12} />
          High queue pressure — congestion likely
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ font: "500 32px/1 var(--mono)", color: "var(--ink)", letterSpacing: "-0.03em" }}>
          {pct.toFixed(1)}<small style={{ fontSize: "14px", color: "var(--mute)" }}>%</small>
        </div>
        <span className={pressure > 0.7 ? "chip w" : "ok"} style={{ fontSize: "11px" }}>
          {pressure > 0.7 ? "⚠ High buffer load" : "✓ Nominal buffer load"}
        </span>
      </div>

      <div className="bar" style={{ margin: "8px 0 14px", height: "6px" }}>
        <u style={{ width: `${Math.max(2, pct)}%`, background: pressure > 0.7 ? "var(--amber)" : "var(--acc)" }} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", fontSize: "12px", fontFamily: "var(--mono)" }}>
        <div style={{ background: "var(--bg)", padding: "8px 10px", borderRadius: "8px", border: "1px solid var(--line)" }}>
          <span style={{ color: "var(--mute)", display: "block", fontSize: "11px" }}>Queued packets</span>
          <b style={{ color: "var(--ink)", fontSize: "14px" }}>{totalPackets.toLocaleString()}</b>
        </div>
        <div style={{ background: "var(--bg)", padding: "8px 10px", borderRadius: "8px", border: "1px solid var(--line)" }}>
          <span style={{ color: "var(--mute)", display: "block", fontSize: "11px" }}>Total capacity</span>
          <b style={{ color: "var(--ink)", fontSize: "14px" }}>
            {totalCapacity > 0 ? totalCapacity.toLocaleString() : "—"}
          </b>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "var(--mute)", marginTop: "10px" }}>
        <span>Active interfaces</span>
        <span style={{ fontFamily: "var(--mono)", color: "var(--ink)" }}>
          {interfaceCount > 0 ? `${backlogged} / ${interfaceCount} queues` : "—"}
        </span>
      </div>
    </div>
  );
}

// ── RouteChurnCounter ────────────────────────────────────────────────────────

export function RouteChurnCounter({
  events,
  policy,
}: {
  events: RunEvent[];
  policy: string;
}) {
  const routeEvents = events.filter((e) => {
    const t = e.title.toLowerCase();
    const k = e.kind.toLowerCase();
    return (
      k === "route_change" ||
      k.includes("route") ||
      t.includes("route") ||
      t.includes("handover") ||
      t.includes("topology")
    );
  });
  const count = routeEvents.length;
  const first = routeEvents.reduce<number | null>(
    (min, event) => (min == null || event.time_s < min ? event.time_s : min),
    null,
  );
  const latest = routeEvents.reduce<number | null>(
    (max, event) => (max == null || event.time_s > max ? event.time_s : max),
    null,
  );

  return (
    <div style={{ marginTop: "8px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ font: "500 32px/1 var(--mono)", color: "var(--ink)", letterSpacing: "-0.03em" }}>
          {count} <small style={{ fontSize: "14px", color: "var(--mute)" }}>route changes</small>
        </div>
        <span className="ok" style={{ fontSize: "11px" }}>
          {count === 0 ? "✓ No route changes" : `${count} recorded changes`}
        </span>
      </div>

      <div className="bar" style={{ margin: "8px 0 14px", height: "6px" }}>
        <u style={{ width: `${Math.min(100, Math.max(5, count * 15))}%`, background: "var(--acc)" }} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", fontSize: "12px", fontFamily: "var(--mono)" }}>
        <div style={{ background: "var(--bg)", padding: "8px 10px", borderRadius: "8px", border: "1px solid var(--line)" }}>
          <span style={{ color: "var(--mute)", display: "block", fontSize: "11px" }}>First change</span>
          <b style={{ color: "var(--ink)", fontSize: "14px" }}>
            {first != null ? `${first.toFixed(2)} s` : "None"}
          </b>
        </div>
        <div style={{ background: "var(--bg)", padding: "8px 10px", borderRadius: "8px", border: "1px solid var(--line)" }}>
          <span style={{ color: "var(--mute)", display: "block", fontSize: "11px" }}>Latest change</span>
          <b style={{ color: "var(--ink)", fontSize: "14px" }}>
            {latest != null ? `${latest.toFixed(2)} s` : "None"}
          </b>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "var(--mute)", marginTop: "10px" }}>
        <span>Routing policy</span>
        <span style={{ fontFamily: "var(--mono)", color: "var(--ink)" }}>
          {policy}
        </span>
      </div>
    </div>
  );
}
