import { useId } from "react";
import { TriangleAlert } from "lucide-react";
import { queuePeak } from "../lib/model";
import type { Frame, LinkData, Metrics, RunEvent, Scenario } from "../lib/types";

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
  const max = Math.max(1, ...values);
  return (
    <svg className="sparkline" viewBox="0 0 90 26" aria-hidden="true">
      <polyline
        points={values
          .map(
            (v, i) =>
              `${(i / Math.max(1, values.length - 1)) * 90},${24 - (v / max) * 20}`,
          )
          .join(" ")}
        stroke={color}
        fill="none"
        strokeWidth="1.5"
      />
    </svg>
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

  const controlDeadline =
    (targets?.["CONTROL"]?.deadline_s ?? 0.05) * 1000;
  const realtimeDeadline =
    (targets?.["REALTIME"]?.deadline_s ?? 0.1) * 1000;

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
      classColor: "#60a5fa",
      target: `${controlDeadline.toFixed(0)} ms target`,
    },
    {
      label: "REALTIME",
      ratio: realtimeRatio,
      classColor: "#a78bfa",
      target: `${realtimeDeadline.toFixed(0)} ms target`,
    },
    {
      label: "BULK",
      ratio: bulkRatio,
      classColor: "#34d399",
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
            {target && (
              <div
                style={{
                  paddingLeft: "68px",
                  fontSize: "8px",
                  color: "var(--muted, #5a7a8a)",
                  marginTop: "2px",
                }}
              >
                {target}
              </div>
            )}
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
  queues: Frame["queues"];
  links: LinkData[];
}) {
  const totalPackets = queues.reduce((sum, q) => sum + (q.packets ?? 0), 0);
  const maxQueue = links.reduce((sum, l) => sum + l.queue_packets * 2, 0);
  const pressure = maxQueue > 0 ? totalPackets / maxQueue : 0;

  const fillColor = pressure > 0.7 ? "#f59e0b" : "#4e8fa8";
  const pct = Math.min(pressure * 100, 100);

  return (
    <div className="queue-breakdown">
      {pressure > 0.7 && (
        <div className="congestion-alert">
          <TriangleAlert size={12} />
          High queue pressure — congestion likely
        </div>
      )}
      <div className="queue-class-row">
        <span className="deadline-bar-label">TOTAL QUEUE</span>
        <div className="deadline-bar-bg">
          <div
            className="deadline-bar-fill"
            style={{ width: `${pct}%`, background: fillColor }}
          />
        </div>
        <span className="deadline-bar-value">
          {totalPackets}/{maxQueue}
        </span>
      </div>
    </div>
  );
}

// ── RouteChurnCounter ────────────────────────────────────────────────────────

export function RouteChurnCounter({ events }: { events: RunEvent[] }) {
  const count = events.filter((e) => {
    const t = e.title.toLowerCase();
    return (
      e.kind === "route_change" ||
      t.includes("route") ||
      t.includes("handover")
    );
  }).length;

  return (
    <div className="route-churn-row">
      <span>Route changes</span>
      <span className="churn-count">{count}</span>
    </div>
  );
}
