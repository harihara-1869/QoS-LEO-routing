import { describe, it, expect } from "vitest";
import {
  frameAt,
  framePair,
  format,
  scenarioDiff,
  validateScenario,
  queuePeak,
  utcClock,
} from "./model";
import type { Replay, Frame, Scenario } from "./types";
const frame = (time_s: number) =>
  ({
    time_s,
    positions: [],
    links: [],
    metrics: null,
    routes: [],
    queues: [],
  }) as Frame;
const replay = { frames: [frame(0), frame(0.1), frame(0.3)] } as Replay;
const config = {
  schema_version: 1,
  epoch: "2025-01-01T00:00:00Z",
  seed: 7,
  duration_s: 5,
  step_s: 0.1,
  control_interval_s: 0.05,
  orbital_start_s: 12,
  constellation: {
    n_planes: 10,
    sats_per_plane: 20,
    inclination: 53,
    altitude_km: 550,
  },
  ground_stations: [],
  flows: [],
  links: {},
  network: {},
  qos: {},
  prediction: {},
} as Scenario;

describe("authoritative cursor semantics", () => {
  it("holds discrete state until its observation timestamp", () => {
    expect(frameAt(replay, 0.299)?.time_s).toBe(0.1);
    expect(frameAt(replay, 0.3)?.time_s).toBe(0.3);
    expect(frameAt(replay, -1)?.time_s).toBe(0);
  });
  it("interpolates only geometry between bracketing frames", () => {
    const [a, b, alpha] = framePair(replay, 0.2);
    expect([a.time_s, b.time_s]).toEqual([0.1, 0.3]);
    expect(alpha).toBeCloseTo(0.5);
  });
  it("preserves unavailable values and historical clock gaps", () => {
    expect(format.percent(null)).toBe("—");
    expect(format.ms(null)).toBe("—");
    expect(utcClock("missing", 1)).toBe("Unavailable");
    expect(utcClock(config.epoch, 13.25)).toBe("00:00:13.250");
  });
  it("does not invent queue packets from compact byte-only controls", () => {
    expect(
      queuePeak({
        ...frame(0),
        queues: [{ link_id: 1, direction: 0, bytes: 500 }],
      }),
    ).toBeNull();
    expect(
      queuePeak({
        ...frame(0),
        queues: [{ link_id: 1, direction: 0, packets: 0 }],
      }),
    ).toBe(0);
  });
});
describe("experiment integrity", () => {
  it("rejects malformed scenario imports without replacing the draft", () => {
    expect(() => validateScenario({ schema_version: 1, flows: [] })).toThrow();
    expect(validateScenario(config)).toEqual(config);
  });
  it("detects demand, epoch and physical differences, independently of cosmetics", () => {
    expect(scenarioDiff(config, { ...config, seed: 8 })).toEqual(["seed"]);
    expect(
      scenarioDiff(config, {
        ...config,
        constellation: { ...config.constellation, altitude_km: 600 },
      }),
    ).toEqual(["constellation"]);
    expect(scenarioDiff(config, structuredClone(config))).toEqual([]);
    expect(
      scenarioDiff(config, {
        ...config,
        constellation: {
          altitude_km: 550,
          inclination: 53,
          sats_per_plane: 20,
          n_planes: 10,
        },
      }),
    ).toEqual([]);
  });
});
