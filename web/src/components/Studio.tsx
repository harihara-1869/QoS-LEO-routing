import { useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
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
  const [tab, setTab] = useState("Orbit");
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
  const n = (
    label: string,
    value: number,
    change: (v: number) => void,
    unit = "",
    min = 0,
    step = 1,
  ) => (
    <label className="field">
      <span>
        {label}
        <small>{unit}</small>
      </span>
      <input
        aria-label={label}
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(e) => change(Number(e.target.value))}
      />
    </label>
  );
  return (
    <div className="studio-content">
      <div className="panel-intro">
        <span className="eyebrow">CONSTELLATION STUDIO</span>
        <h2>Build your orbit.</h2>
        <p>Define the network. Explore the possibilities.</p>
      </div>
      <div className="preset-select">
        <span>START WITH A PRESET</span>
        <select
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
        <ChevronDown size={14} />
      </div>
      <div className="panel-tabs">
        {["Orbit", "Ground", "Traffic", "Advanced"].map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "Orbit" && (
        <>
          <div className="section-heading">
            <h3>Walker constellation</h3>
            <span>{amount.satellites} SATELLITES</span>
          </div>
          <div className="field-grid">
            {n(
              "Orbital planes",
              scenario.constellation.n_planes,
              (v) =>
                mutate((d) => {
                  d.constellation.n_planes = v;
                }),
              "planes",
              1,
            )}
            {n(
              "Satellites per plane",
              scenario.constellation.sats_per_plane,
              (v) =>
                mutate((d) => {
                  d.constellation.sats_per_plane = v;
                }),
              "satellites",
              1,
            )}
            {n(
              "Altitude",
              scenario.constellation.altitude_km,
              (v) =>
                mutate((d) => {
                  d.constellation.altitude_km = v;
                }),
              "km",
              100,
              10,
            )}
            {n(
              "Inclination",
              scenario.constellation.inclination,
              (v) =>
                mutate((d) => {
                  d.constellation.inclination = v;
                }),
              "°",
              0,
              0.1,
            )}
            {n(
              "Walker phasing",
              scenario.constellation.phasing_f ?? 1,
              (v) =>
                mutate((d) => {
                  d.constellation.phasing_f = v;
                }),
              "F",
              0,
            )}
            {n(
              "Orbital start offset",
              scenario.orbital_start_s ?? 0,
              (v) =>
                mutate((d) => {
                  d.orbital_start_s = v;
                }),
              "s",
              0,
              0.1,
            )}
          </div>
          <label className="field full">
            <span>
              Reference epoch<small>UTC</small>
            </span>
            <input
              aria-label="Reference epoch"
              value={scenario.epoch}
              onChange={(e) =>
                mutate((d) => {
                  d.epoch = e.target.value;
                })
              }
            />
          </label>
          <div className="info-note">
            <span className="tiny-orbit" />
            Geometry is propagated by the Python orbital model. Preview motion
            never represents packet delivery.
          </div>
          <div className="section-heading">
            <h3>Mission window</h3>
          </div>
          <div className="field-grid">
            {n(
              "Duration",
              scenario.duration_s,
              (v) =>
                mutate((d) => {
                  d.duration_s = v;
                  if (v > 0) {
                    d.flows.forEach((f) => {
                      if (f.end_time > v) f.end_time = v;
                    });
                  }
                }),
              "s",
              0.1,
              0.1,
            )}
            {n(
              "Random seed",
              scenario.seed,
              (v) =>
                mutate((d) => {
                  d.seed = v;
                }),
              "",
              1,
            )}
            {n(
              "Topology interval",
              scenario.step_s,
              (v) =>
                mutate((d) => {
                  d.step_s = v;
                }),
              "s",
              0.01,
              0.01,
            )}
            {n(
              "Control interval",
              scenario.control_interval_s,
              (v) =>
                mutate((d) => {
                  d.control_interval_s = v;
                }),
              "s",
              0.01,
              0.01,
            )}
          </div>
        </>
      )}
      {tab === "Ground" && (
        <>
          <div className="section-heading">
            <h3>Ground network</h3>
            <button
              className={`text-button ${placing ? "mint" : ""}`}
              onClick={onPlace}
            >
              <MapPin size={13} />
              {placing ? "Double-click Earth" : "Place on Earth"}
            </button>
          </div>
          {scenario.ground_stations.map((g, i) => (
            <div className="station-editor" key={i}>
              <div className="station-editor-title">
                <MapPin size={14} />
                <input
                  aria-label={`Station ${i + 1} name`}
                  value={g[0]}
                  onChange={(e) =>
                    mutate((d) => {
                      d.ground_stations[i][0] = e.target.value;
                    })
                  }
                />
                <button
                  className="icon-button"
                  aria-label={`Remove ${g[0]}`}
                  onClick={() =>
                    mutate((d) => {
                      d.ground_stations.splice(i, 1);
                    })
                  }
                >
                  <Trash2 size={13} />
                </button>
              </div>
              <div className="field-grid">
                {n(
                  `Latitude ${i + 1}`,
                  g[1],
                  (v) =>
                    mutate((d) => {
                      d.ground_stations[i][1] = v;
                    }),
                  "°",
                  -90,
                  0.001,
                )}
                {n(
                  `Longitude ${i + 1}`,
                  g[2],
                  (v) =>
                    mutate((d) => {
                      d.ground_stations[i][2] = v;
                    }),
                  "°",
                  -180,
                  0.001,
                )}
              </div>
              {n(
                `Elevation ${i + 1}`,
                g[3],
                (v) =>
                  mutate((d) => {
                    d.ground_stations[i][3] = v;
                  }),
                "m",
                0,
                1,
              )}
            </div>
          ))}
          <button
            className="secondary-button full"
            onClick={() =>
              mutate((d) => {
                d.ground_stations.push([
                  `GS_${d.ground_stations.length + 1}`,
                  0,
                  0,
                  0,
                ]);
              })
            }
          >
            <Plus size={14} />
            Add ground station
          </button>
          <label className="toggle-line">
            <span>
              Allow gateway transit
              <small>Ground stations may relay satellite traffic</small>
            </span>
            <input
              type="checkbox"
              checked={scenario.allow_ground_transit ?? true}
              onChange={(e) =>
                mutate((d) => {
                  d.allow_ground_transit = e.target.checked;
                })
              }
            />
          </label>
        </>
      )}
      {tab === "Traffic" && (
        <>
          <div className="section-heading">
            <h3>Traffic applications</h3>
            <span>{scenario.flows.length} FLOWS</span>
          </div>
          {scenario.flows.map((f, i) => (
            <details className="flow-editor" key={f.flow_id} open={i === 0}>
              <summary>
                <i className={`class-dot ${f.flow_type.toLowerCase()}`} />
                <b>Flow {String(f.flow_id).padStart(2, "0")}</b>
                <span>{f.flow_type}</span>
                <ChevronDown size={13} />
              </summary>
              <div className="field-grid">
                <label className="field">
                  <span>Service class</span>
                  <select
                    value={f.flow_type}
                    onChange={(e) =>
                      mutate((d) => {
                        d.flows[i].flow_type = e.target
                          .value as Traffic["flow_type"];
                      })
                    }
                  >
                    {["CONTROL", "REALTIME", "BULK"].map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Protocol</span>
                  <select
                    value={f.protocol ?? "udp"}
                    onChange={(e) =>
                      mutate((d) => {
                        d.flows[i].protocol = e.target.value as "udp" | "tcp";
                        if (e.target.value === "tcp") {
                          d.flows[i].flow_type = "BULK";
                          d.flows[i].data_rate_bps = 0;
                          d.flows[i].max_bytes = 100000;
                        } else delete d.flows[i].max_bytes;
                      })
                    }
                  >
                    <option value="udp">UDP · paced</option>
                    <option value="tcp">TCP · Linux Reno</option>
                  </select>
                </label>
                {(["src", "dst"] as const).map((key) => (
                  <label className="field" key={key}>
                    <span>{key === "src" ? "Source" : "Destination"}</span>
                    <select
                      value={f[key]}
                      onChange={(e) =>
                        mutate((d) => {
                          d.flows[i][key] = e.target.value;
                        })
                      }
                    >
                      {scenario.ground_stations.map((g) => (
                        <option key={g[0]}>{g[0]}</option>
                      ))}
                      {!scenario.ground_stations.some(
                        (g) => g[0] === f[key],
                      ) && <option>{f[key]}</option>}
                    </select>
                  </label>
                ))}
                {n(
                  "Start time",
                  f.start_time,
                  (v) =>
                    mutate((d) => {
                      d.flows[i].start_time = v;
                    }),
                  "s",
                  0,
                  0.01,
                )}
                {n(
                  "End time",
                  f.end_time,
                  (v) =>
                    mutate((d) => {
                      d.flows[i].end_time = v;
                    }),
                  "s",
                  0.01,
                  0.01,
                )}
                {n(
                  "Payload size",
                  f.packet_size_bytes,
                  (v) =>
                    mutate((d) => {
                      d.flows[i].packet_size_bytes = v;
                    }),
                  "bytes",
                  1,
                )}
                {f.protocol === "tcp"
                  ? n(
                      "Transfer bytes",
                      f.max_bytes ?? 100000,
                      (v) =>
                        mutate((d) => {
                          d.flows[i].max_bytes = v;
                        }),
                      "bytes",
                      1,
                    )
                  : n(
                      "Offered rate",
                      f.data_rate_bps ?? 0,
                      (v) =>
                        mutate((d) => {
                          d.flows[i].data_rate_bps = v;
                        }),
                      "bps",
                      0,
                      1000,
                    )}
              </div>
              <button
                className="text-button danger"
                onClick={() =>
                  mutate((d) => {
                    d.flows.splice(i, 1);
                  })
                }
              >
                <Trash2 size={12} />
                Remove flow
              </button>
            </details>
          ))}
          <button
            className="secondary-button full"
            onClick={() =>
              mutate((d) => {
                d.flows.push({
                  flow_id: Math.max(0, ...d.flows.map((f) => f.flow_id)) + 1,
                  flow_type: "BULK",
                  protocol: "udp",
                  src: d.ground_stations[0]?.[0] ?? "",
                  dst: d.ground_stations[1]?.[0] ?? "",
                  start_time: 0,
                  end_time: d.duration_s,
                  packet_size_bytes: 1200,
                  data_rate_bps: 24000,
                });
              })
            }
          >
            <Plus size={14} />
            Add traffic flow
          </button>
          <button
            className="secondary-button full"
            onClick={() => onChange(randomizeGroundPairs(scenario))}
          >
            <RefreshCw size={14} />
            Randomize ground pairs · seed {scenario.seed}
          </button>
          <div className="info-note">
            Each flow is one ground-station-to-ground-station path. Randomize
            assigns distinct pairs from the current seed; change the seed and
            randomize again for different pairings.
          </div>
        </>
      )}
      {tab === "Advanced" && (
        <>
          <div className="section-heading">
            <h3>Link and terminal model</h3>
          </div>
          <div className="field-grid">
            {Object.entries(scenario.links)
              .filter(([, v]) => typeof v === "number")
              .map(([k, v]) =>
                n(
                  k.replaceAll("_", " "),
                  v as number,
                  (value) =>
                    mutate((d) => {
                      d.links[k] = value;
                    }),
                  k.endsWith("_s")
                    ? "s"
                    : k.endsWith("_bps")
                      ? "bps"
                      : k.endsWith("_deg")
                        ? "°"
                        : "",
                  0,
                  k.endsWith("_s") ? 0.05 : 1,
                ),
              )}
          </div>
          {Object.entries(scenario.links)
            .filter(([, v]) => typeof v === "boolean")
            .map(([k, v]) => (
              <label className="toggle-line" key={k}>
                <span>{k.replaceAll("_", " ")}</span>
                <input
                  type="checkbox"
                  checked={Boolean(v)}
                  onChange={(e) =>
                    mutate((d) => {
                      d.links[k] = e.target.checked;
                    })
                  }
                />
              </label>
            ))}
          <div className="section-heading">
            <h3>Packet network</h3>
          </div>
          <div className="field-grid">
            {Object.entries(scenario.network).map(([k, v]) =>
              n(
                k.replaceAll("_", " "),
                v,
                (value) =>
                  mutate((d) => {
                    d.network[k] = value;
                  }),
                "",
                1,
              ),
            )}
          </div>
          <div className="section-heading">
            <h3>Forecast configuration</h3>
          </div>
          <div className="field-grid">
            {Object.entries(scenario.prediction).map(([k, v]) =>
              n(
                k.replaceAll("_", " "),
                v,
                (value) =>
                  mutate((d) => {
                    d.prediction[k] = value;
                  }),
                "",
                0,
                0.01,
              ),
            )}
          </div>
        </>
      )}
      <div className="configuration-tools">
        <button onClick={() => file.current?.click()}>
          <Upload size={13} />
          Import JSON
        </button>
        <button onClick={() => download(scenario, "leo-scenario.json")}>
          <Download size={13} />
          Export
        </button>
        <button
          onClick={() => {
            setShowJson(!showJson);
            setJson(JSON.stringify(scenario, null, 2));
          }}
        >
          <FileJson size={13} />
          JSON
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
      {fileError && <p className="error-text">{fileError}</p>}
      {showJson && (
        <div className="json-editor">
          <textarea
            aria-label="Scenario JSON"
            value={json}
            onChange={(e) => setJson(e.target.value)}
          />
          <button
            className="secondary-button"
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
            <Check size={13} />
            Apply JSON
          </button>
        </div>
      )}
      <div className="studio-footer">
        <div className="estimate">
          <span>
            {format.number(amount.packets)} <small>estimated packets</small>
          </span>
          <span>
            {format.number(amount.updates)} <small>control ticks</small>
          </span>
        </div>
        <div className="button-row">
          <button className="secondary-button" onClick={onSave}>
            <Save size={14} />
            Save design
          </button>
          <button
            className="primary-button"
            disabled={busy}
            onClick={onPreview}
          >
            {busy ? (
              <RefreshCw size={14} className="spin" />
            ) : (
              <ArrowUpRight size={15} />
            )}
            Generate preview
          </button>
        </div>
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
