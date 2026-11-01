import { useId } from "react";
import { queuePeak } from "../lib/model";
import type { Frame } from "../lib/types";
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
