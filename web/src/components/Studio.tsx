import { useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Download,
  FileJson,
  MapPin,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import type { Replay, Scenario, Traffic } from "../lib/types";
import {
  estimate,
  format,
  randomizeGroundPairs,
  validateScenario,
} from "../lib/model";
import { download } from "../lib/api";

export function Studio({
  scenario,
  onChange,
  presets,
  onPreset,
  onPreview,
  onSave,
  busy,
  onPlace,
  placing,
}: {
  scenario: Scenario;
  onChange: (c: Scenario) => void;
  presets: { id: string; name: string; scenario: Scenario }[];
  onPreset: (s: Scenario) => void;
  onPreview: () => void;
  onSave: () => void;
  busy: boolean;
  onPlace: () => void;
  placing: boolean;
}) {
  const [tab, setTab] = useState<"Orbit" | "Ground" | "Traffic" | "Advanced">("Orbit");
  const [fileError, setFileError] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const [json, setJson] = useState("");
  const [showJson, setShowJson] = useState(false);

  const mutate = (fn: (d: Scenario) => void) => {
    const d = structuredClone(scenario);
    fn(d);
    onChange(d);
  };

  const amount = estimate(scenario);

  return (
    <div className="card form studio-form">
      <div>
        <h2 style={{ margin: "0 0 4px", fontSize: "22px", letterSpacing: "-0.02em" }}>
          Build your orbit
        </h2>
        <p className="sub" style={{ margin: 0, fontSize: "14px" }}>
          Define the network. Explore the possibilities.
        </p>
      </div>

      <label style={{ display: "block", marginTop: "12px" }}>
        Start with a preset
        <select
          className="sel"
          aria-label="Scenario preset"
          defaultValue=""
          onChange={(e) => {
            const p = presets.find((p) => p.id === e.target.value);
            if (p) onPreset(structuredClone(p.scenario));
          }}
        >
          <option value="" disabled>
            Select a mission template
          </option>
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>

      <div className="tabs">
        {(["Orbit", "Ground", "Traffic", "Advanced"] as const).map((t) => (
          <button
            key={t}
            className={tab === t ? "on" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Orbit" && (
        <div className="pane on">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
            <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mute)", textTransform: "uppercase" }}>
              Walker Constellation
            </span>
            <span className="badge">{amount.satellites} satellites</span>
          </div>

          <div className="fg">
            <label>
              Orbital planes
              <input
                type="number"
                min={1}
                max={30}
                value={scenario.constellation.n_planes}
                onChange={(e) =>
                  mutate((d) => {
                    d.constellation.n_planes = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Satellites per plane
              <input
                type="number"
                min={1}
                max={60}
                value={scenario.constellation.sats_per_plane}
                onChange={(e) =>
                  mutate((d) => {
                    d.constellation.sats_per_plane = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Altitude (km)
              <input
                type="number"
                min={100}
                max={2000}
                step={10}
                value={scenario.constellation.altitude_km}
                onChange={(e) =>
                  mutate((d) => {
                    d.constellation.altitude_km = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Inclination (°)
              <input
                type="number"
                min={0}
                max={98}
                step={0.1}
                value={scenario.constellation.inclination}
                onChange={(e) =>
                  mutate((d) => {
                    d.constellation.inclination = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Walker phasing
              <input
                type="number"
                min={0}
                value={scenario.constellation.phasing_f ?? 1}
                onChange={(e) =>
                  mutate((d) => {
                    d.constellation.phasing_f = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Orbital start offset (s)
              <input
                type="number"
                min={0}
                value={scenario.orbital_start_s ?? 0}
                onChange={(e) =>
                  mutate((d) => {
                    d.orbital_start_s = Number(e.target.value);
                  })
                }
              />
            </label>
          </div>

          <label style={{ marginTop: "12px", display: "block" }}>
            Reference epoch (UTC)
            <input
              value={scenario.epoch}
              onChange={(e) =>
                mutate((d) => {
                  d.epoch = e.target.value;
                })
              }
            />
          </label>

          <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid var(--line)" }}>
            <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mute)", textTransform: "uppercase", display: "block", marginBottom: "8px" }}>
              Mission Window
            </span>
            <div className="fg">
              <label>
                Duration (s)
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={scenario.duration_s}
                  onChange={(e) =>
                    mutate((d) => {
                      const v = Number(e.target.value);
                      d.duration_s = v;
                      if (v > 0) {
                        d.flows.forEach((f) => {
                          if (f.end_time > v) f.end_time = v;
                        });
                      }
                    })
                  }
                />
              </label>
              <label>
                Random seed
                <input
                  type="number"
                  value={scenario.seed}
                  onChange={(e) =>
                    mutate((d) => {
                      d.seed = Number(e.target.value);
                    })
                  }
                />
              </label>
              <label>
                Topology interval (s)
                <input
                  type="number"
                  step={0.01}
                  value={scenario.step_s}
                  onChange={(e) =>
                    mutate((d) => {
                      d.step_s = Number(e.target.value);
                    })
                  }
                />
              </label>
              <label>
                Control interval (s)
                <input
                  type="number"
                  step={0.01}
                  value={scenario.control_interval_s}
                  onChange={(e) =>
                    mutate((d) => {
                      d.control_interval_s = Number(e.target.value);
                    })
                  }
                />
              </label>
            </div>
          </div>
        </div>
      )}

      {tab === "Ground" && (
        <div className="pane on">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mute)", textTransform: "uppercase" }}>
                Ground Network
              </span>
              <span className="badge">{scenario.ground_stations.length} stations</span>
            </div>
            <button
              className={`btn ${placing ? "pri" : ""}`}
              style={{ padding: "4px 10px", fontSize: "12px" }}
              onClick={onPlace}
            >
              <MapPin size={12} />
              {placing ? "Click on Earth" : "Place on Earth"}
            </button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "360px", overflowY: "auto", paddingRight: "4px" }}>
            {scenario.ground_stations.map((g, i) => (
              <div key={i} className="station-item">
                <div className="station-header">
                  <MapPin size={14} style={{ color: "var(--acc)" }} />
                  <input
                    aria-label={`Station ${i + 1} name`}
                    value={g[0]}
                    placeholder="Station ID"
                    onChange={(e) =>
                      mutate((d) => {
                        d.ground_stations[i][0] = e.target.value;
                      })
                    }
                  />
                  <button
                    className="station-delete-btn"
                    title={`Remove ${g[0]}`}
                    onClick={() =>
                      mutate((d) => {
                        d.ground_stations.splice(i, 1);
                      })
                    }
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                <div className="station-coords">
                  <label>
                    Lat (°)
                    <input
                      type="number"
                      step={0.01}
                      value={g[1]}
                      onChange={(e) =>
                        mutate((d) => {
                          d.ground_stations[i][1] = Number(e.target.value);
                        })
                      }
                    />
                  </label>
                  <label>
                    Lon (°)
                    <input
                      type="number"
                      step={0.01}
                      value={g[2]}
                      onChange={(e) =>
                        mutate((d) => {
                          d.ground_stations[i][2] = Number(e.target.value);
                        })
                      }
                    />
                  </label>
                  <label>
                    Elev (m)
                    <input
                      type="number"
                      step={10}
                      value={g[3]}
                      onChange={(e) =>
                        mutate((d) => {
                          d.ground_stations[i][3] = Number(e.target.value);
                        })
                      }
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", gap: "8px", marginTop: "10px" }}>
            <button
              className="btn"
              style={{ flex: 1, fontSize: "12px", justifyContent: "center" }}
              onClick={() =>
                mutate((d) => {
                  d.ground_stations.push([
                    `GS_${d.ground_stations.length + 1}`,
                    19.076,
                    72.8777,
                    10,
                  ]);
                })
              }
            >
              <Plus size={13} /> Add station
            </button>
            <button
              className="btn"
              style={{ fontSize: "12px", justifyContent: "center" }}
              title="Generate random ground-pair pairs"
              onClick={() =>
                mutate((d) => {
                  randomizeGroundPairs(d);
                })
              }
            >
              Randomize pairs
            </button>
          </div>
        </div>
      )}

      {tab === "Traffic" && (
        <div className="pane on">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mute)", textTransform: "uppercase" }}>
                Traffic Flows
              </span>
              <span className="badge">{scenario.flows.length} active</span>
            </div>
            <button
              className="btn"
              style={{ padding: "4px 10px", fontSize: "12px" }}
              onClick={() =>
                mutate((d) => {
                  const s = d.ground_stations[0]?.[0] ?? "GS_1";
                  const t = d.ground_stations[1]?.[0] ?? s;
                  d.flows.push({
                    flow_id: (d.flows.at(-1)?.flow_id ?? 0) + 1,
                    flow_type: "REALTIME",
                    protocol: "udp",
                    src: s,
                    dst: t,
                    data_rate_bps: 1000000,
                    start_time: 0,
                    end_time: d.duration_s,
                    deadline_s: 0.1,
                    packet_size_bytes: 1400,
                  });
                })
              }
            >
              <Plus size={12} /> Add flow
            </button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "360px", overflowY: "auto", paddingRight: "4px" }}>
            {scenario.flows.map((f, i) => (
              <div key={f.flow_id} className="station-item">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span style={{ font: "600 13px var(--mono)" }}>Flow {f.flow_id}</span>
                    <select
                      className="sel"
                      style={{ padding: "3px 8px", width: "auto", fontSize: "11px" }}
                      value={f.flow_type}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i].flow_type = e.target.value as Traffic["flow_type"];
                        })
                      }
                    >
                      <option value="CONTROL">CONTROL</option>
                      <option value="REALTIME">REALTIME</option>
                      <option value="BULK">BULK</option>
                    </select>
                  </div>
                  <button
                    className="station-delete-btn"
                    title="Remove flow"
                    onClick={() =>
                      mutate((d) => {
                        d.flows.splice(i, 1);
                      })
                    }
                  >
                    <Trash2 size={12} />
                  </button>
                </div>

                <div className="fg" style={{ marginTop: "4px" }}>
                  <label>
                    Source
                    <select
                      className="sel"
                      value={f.src}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i].src = e.target.value;
                        })
                      }
                    >
                      {scenario.ground_stations.map((g) => (
                        <option key={g[0]} value={g[0]}>
                          {g[0]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Target
                    <select
                      className="sel"
                      value={f.dst}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i].dst = e.target.value;
                        })
                      }
                    >
                      {scenario.ground_stations.map((g) => (
                        <option key={g[0]} value={g[0]}>
                          {g[0]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="station-coords" style={{ marginTop: "4px" }}>
                  <label>
                    Rate (kbps)
                    <input
                      type="number"
                      step={100}
                      value={((f.data_rate_bps ?? 1000000) / 1000).toFixed(0)}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i].data_rate_bps = Number(e.target.value) * 1000;
                        })
                      }
                    />
                  </label>
                  <label>
                    Deadline (ms)
                    <input
                      type="number"
                      step={10}
                      value={((f.deadline_s ?? 0.1) * 1000).toFixed(0)}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i].deadline_s = Number(e.target.value) / 1000;
                        })
                      }
                    />
                  </label>
                  <label>
                    Duration (s)
                    <input
                      type="number"
                      step={0.5}
                      value={f.end_time}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i].end_time = Number(e.target.value);
                        })
                      }
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "Advanced" && (
        <div className="pane on">
          <span style={{ fontSize: "12px", fontFamily: "var(--mono)", color: "var(--mute)", textTransform: "uppercase", display: "block", marginBottom: "8px" }}>
            Link & Routing Parameters
          </span>
          <div className="fg">
            <label>
              Max ISL range (km)
              <input
                type="number"
                value={Number(scenario.links.max_isl_distance_km ?? 5014)}
                onChange={(e) =>
                  mutate((d) => {
                    d.links.max_isl_distance_km = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Max GSL range (km)
              <input
                type="number"
                value={Number(scenario.links.max_gsl_distance_km ?? 2000)}
                onChange={(e) =>
                  mutate((d) => {
                    d.links.max_gsl_distance_km = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Data rate (Mbps)
              <input
                type="number"
                value={scenario.network.data_rate_mbps ?? 10}
                onChange={(e) =>
                  mutate((d) => {
                    d.network.data_rate_mbps = Number(e.target.value);
                  })
                }
              />
            </label>
            <label>
              Buffer queue (pkts)
              <input
                type="number"
                value={scenario.network.queue_capacity_packets ?? 500}
                onChange={(e) =>
                  mutate((d) => {
                    d.network.queue_capacity_packets = Number(e.target.value);
                  })
                }
              />
            </label>
          </div>

          <div style={{ display: "flex", gap: "8px", marginTop: "14px" }}>
            <button className="btn" style={{ flex: 1, fontSize: "12px", justifyContent: "center" }} onClick={() => file.current?.click()}>
              <Upload size={13} /> Import JSON
            </button>
            <button className="btn" style={{ flex: 1, fontSize: "12px", justifyContent: "center" }} onClick={() => download(scenario, "leo-scenario.json")}>
              <Download size={13} /> Export JSON
            </button>
            <button
              className="btn"
              style={{ fontSize: "12px", justifyContent: "center" }}
              onClick={() => {
                setShowJson(!showJson);
                setJson(JSON.stringify(scenario, null, 2));
              }}
            >
              <FileJson size={13} /> Edit
            </button>
          </div>
          <input
            ref={file}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f)
                try {
                  const c = validateScenario(JSON.parse(await f.text()));
                  onChange(c);
                  setFileError("");
                } catch (err) {
                  setFileError(String(err));
                }
              e.target.value = "";
            }}
          />
          {fileError && <p style={{ color: "var(--bad)", fontSize: "12px", margin: "6px 0 0" }}>{fileError}</p>}
          {showJson && (
            <div style={{ marginTop: "10px" }}>
              <textarea
                aria-label="Scenario JSON"
                style={{ width: "100%", height: "160px", font: "12px var(--mono)", padding: "8px", background: "var(--field)", border: "1px solid var(--line)", borderRadius: "8px", color: "var(--ink)" }}
                value={json}
                onChange={(e) => setJson(e.target.value)}
              />
              <button
                className="btn pri"
                style={{ marginTop: "6px", width: "100%", fontSize: "12px", justifyContent: "center" }}
                onClick={() => {
                  try {
                    const c = validateScenario(JSON.parse(json));
                    onChange(c);
                    setFileError("");
                    setShowJson(false);
                  } catch (e) {
                    setFileError(String(e));
                  }
                }}
              >
                <Check size={13} /> Apply JSON
              </button>
            </div>
          )}
        </div>
      )}

      <div className="note" style={{ margin: "14px 0 6px", padding: "10px 14px", background: "var(--bg)", borderRadius: "8px", border: "1px solid var(--line)" }}>
        <span>
          <b>{format.number(amount.packets)}</b> estimated packets
        </span>
        <span>
          {amount.satellites} sats · {format.number(amount.updates)} ticks
        </span>
      </div>

      <div className="fg" style={{ marginTop: "6px" }}>
        <button className="btn" style={{ justifyContent: "center" }} onClick={onSave}>
          <Save size={14} /> Save design
        </button>
        <button
          className="btn pri"
          style={{ justifyContent: "center" }}
          disabled={busy}
          onClick={onPreview}
        >
          {busy ? <RefreshCw size={14} className="spin" /> : <ArrowUpRight size={14} />}
          Generate preview
        </button>
      </div>
    </div>
  );
}

export function ScenarioBadge({ run }: { run: Replay }) {
  if (!run.scenario.constellation)
    return <span>Explicit network graph · geometry unavailable</span>;
  return (
    <>
      <span>{run.scenario.constellation.n_planes} planes</span>
      <span>{run.scenario.constellation.altitude_km} km altitude</span>
      <span>{run.scenario.constellation.inclination}° inclination</span>
    </>
  );
}
