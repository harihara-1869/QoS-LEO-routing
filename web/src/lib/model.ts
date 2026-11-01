import type { Frame, Replay, Scenario } from "./types";
export const CLASS_COLORS = {
  CONTROL: "#a8ecd8",
  REALTIME: "#e0b678",
  BULK: "#7aa5e2",
};
export const format = {
  number: (v: number | null | undefined) =>
    v == null
      ? "—"
      : new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(v),
  percent: (v: number | null | undefined) =>
    v == null ? "—" : `${(v * 100).toFixed(1)}%`,
  ms: (v: number | null | undefined) =>
    v == null ? "—" : `${(v * 1000).toFixed(1)}`,
  mbps: (v: number | null | undefined) =>
    v == null ? "—" : (v / 1e6).toFixed(2),
  time: (v: number) => `${v.toFixed(2).padStart(5, "0")} s`,
};
export function frameAt(run: Replay | undefined, t: number): Frame | undefined {
  if (!run?.frames.length) return;
  let low = 0,
    high = run.frames.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (run.frames[middle].time_s <= t + 1e-7) low = middle;
    else high = middle - 1;
  }
  return run.frames[low];
}
export function framePair(run: Replay, t: number): [Frame, Frame, number] {
  const a = frameAt(run, t) ?? run.frames[0],
    index = run.frames.indexOf(a),
    b = run.frames[Math.min(index + 1, run.frames.length - 1)];
  return [
    a,
    b,
    b.time_s > a.time_s
      ? Math.max(0, Math.min(1, (t - a.time_s) / (b.time_s - a.time_s)))
      : 0,
  ];
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}
export function scenarioDiff(a: Scenario, b: Scenario): string[] {
  const keys = [
    "constellation",
    "ground_stations",
    "links",
    "network",
    "qos",
    "flows",
    "seed",
    "epoch",
    "duration_s",
    "step_s",
    "control_interval_s",
    "orbital_start_s",
    "allow_ground_transit",
    "prediction",
  ] as const;
  return keys
    .filter(
      (k) =>
        JSON.stringify(canonical(a[k])) !== JSON.stringify(canonical(b[k])),
    )
    .map((k) => k.replaceAll("_", " "));
}
export function estimate(c: Scenario) {
  return {
    satellites: c.constellation.n_planes * c.constellation.sats_per_plane,
    updates: Math.ceil(c.duration_s / c.control_interval_s),
    packets: Math.round(
      c.flows.reduce(
        (n, f) =>
          n +
          (f.protocol === "udp"
            ? (Math.max(0, Math.min(f.end_time, c.duration_s) - f.start_time) *
                (f.data_rate_bps ?? 0)) /
              (8 * f.packet_size_bytes)
            : 0),
        0,
      ),
    ),
  };
}

/** Return a reason a flow's timing is invalid, or null when all flows are usable. */
export function flowTimingError(c: Scenario): string | null {
  for (const f of c.flows) {
    if (!Number.isFinite(f.end_time) || f.end_time <= 0)
      return `Flow ${f.flow_id} has end time ${f.end_time}; it must be greater than 0.`;
    if (!(f.start_time < Math.min(f.end_time, c.duration_s)))
      return `Flow ${f.flow_id} must start before its end time and the mission duration.`;
  }
  return null;
}

/** Deterministic PRNG (mulberry32) so a seed always yields the same traffic. */
function seeded(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Reassign each flow to a distinct ground-station pair, shuffled by the seed. */
export function randomizeGroundPairs(c: Scenario): Scenario {
  const names = c.ground_stations.map((g) => g[0]);
  if (names.length < 2) return c;
  const pairs: [string, string][] = [];
  for (const a of names)
    for (const b of names) if (a !== b) pairs.push([a, b]);
  const rand = seeded(c.seed);
  for (let i = pairs.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [pairs[i], pairs[j]] = [pairs[j], pairs[i]];
  }
  return {
    ...c,
    flows: c.flows.map((f, i) => {
      const [src, dst] = pairs[i % pairs.length];
      return { ...f, src, dst };
    }),
  };
}

/** Reject malformed editor imports before they can replace a usable draft. */
export function validateScenario(value: unknown): Scenario {
  const c = value as Scenario;
  const finite = (v: unknown) => typeof v === "number" && Number.isFinite(v);
  if (
    !c ||
    typeof c !== "object" ||
    c.schema_version !== 1 ||
    !c.constellation ||
    !Array.isArray(c.ground_stations) ||
    !Array.isArray(c.flows) ||
    !c.links ||
    !c.network ||
    !c.qos ||
    !c.prediction
  )
    throw Error(
      "Import a complete orbital scenario (schema 1), including links, network, QoS and prediction settings.",
    );
  if (!Number.isFinite(Date.parse(c.epoch)))
    throw Error("Epoch must be an ISO date.");
  for (const key of [
    "duration_s",
    "step_s",
    "control_interval_s",
    "seed",
    "orbital_start_s",
  ] as const)
    if (!finite(c[key])) throw Error(`${key} must be a finite number.`);
  for (const key of [
    "n_planes",
    "sats_per_plane",
    "inclination",
    "altitude_km",
  ] as const)
    if (!finite(c.constellation[key]))
      throw Error(`Constellation ${key} must be a finite number.`);
  if (
    !c.ground_stations.every(
      (g) =>
        Array.isArray(g) &&
        g.length === 4 &&
        typeof g[0] === "string" &&
        g.slice(1).every(finite),
    )
  )
    throw Error("Stations need a name, latitude, longitude and elevation.");
  if (
    !c.flows.every(
      (f) =>
        f &&
        typeof f.src === "string" &&
        typeof f.dst === "string" &&
        ["CONTROL", "REALTIME", "BULK"].includes(f.flow_type) &&
        ["udp", "tcp"].includes(f.protocol) &&
        [f.flow_id, f.start_time, f.end_time, f.packet_size_bytes].every(
          finite,
        ),
    )
  )
    throw Error(
      "Each flow needs valid endpoints, class, protocol, timing and payload fields.",
    );
  return c;
}
export function utcClock(epoch: string, seconds: number): string {
  const t = Date.parse(epoch) + seconds * 1000;
  return Number.isFinite(t)
    ? new Date(t).toISOString().slice(11, 23)
    : "Unavailable";
}

export function queuePeak(frame: Frame): number | null {
  return frame.queues.length && frame.queues.every((q) => q.packets != null)
    ? Math.max(...frame.queues.map((q) => q.packets!))
    : null;
}
