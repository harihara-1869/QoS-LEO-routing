import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  Clock3,
  Copy,
  FolderOpen,
  Search,
  Upload,
  X,
  GitCompareArrows,
} from "lucide-react";
import type { Replay, RunRecord } from "../lib/types";
import { format } from "../lib/model";
import { api } from "../lib/api";
export function Library({
  runs,
  onOpen,
  onCompare,
  selected,
  onToggle,
  onDuplicate,
  onRefresh,
  notify,
}: {
  runs: RunRecord[];
  onOpen: (id: string) => void;
  onCompare: () => void;
  selected: string[];
  onToggle: (id: string) => void;
  onDuplicate: (id: string) => void;
  onRefresh: () => void;
  notify: (s: string) => void;
}) {
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState("all"),
    [filterPolicy, setFilterPolicy] = useState("all"),
    [filterScenario, setFilterScenario] = useState("all"),
    [importing, setImporting] = useState(false),
    [candidates, setCandidates] = useState<{ path: string; name: string }[]>(
      [],
    ),
    [busy, setBusy] = useState("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!importing) return;
    const previous = document.activeElement as HTMLElement | null;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setImporting(false);
    };
    window.addEventListener("keydown", close);
    document
      .querySelector<HTMLButtonElement>('[aria-label="Close import"]')
      ?.focus();
    return () => {
      window.removeEventListener("keydown", close);
      previous?.focus();
    };
  }, [importing]);
  const scenarioOptions = [...new Set(runs.map((r) => {
    const name = r.name.toLowerCase();
    if (name.includes("burst")) return "burst";
    if (name.includes("handover")) return "handover";
    if (name.includes("hotspot")) return "hotspot";
    if (name.includes("overload")) return "overload";
    if (name.includes("normal") || name.includes("aurora")) return "normal";
    return "other";
  }))].sort();

  function getScenarioLabel(name: string): string {
    const n = name.toLowerCase();
    if (n.includes("burst")) return "burst";
    if (n.includes("handover")) return "handover";
    if (n.includes("hotspot")) return "hotspot";
    if (n.includes("overload")) return "overload";
    if (n.includes("normal") || n.includes("aurora")) return "normal";
    return "other";
  }

  const policyOptions = [...new Set(runs.map((r) => r.policy))].sort();

  const filtered = runs.filter(
    (r) =>
      (status === "all" || r.status === status) &&
      (filterPolicy === "all" || r.policy === filterPolicy) &&
      (filterScenario === "all" || getScenarioLabel(r.name) === filterScenario) &&
      `${r.name} ${r.policy} ${r.id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  async function imports() {
    try {
      setCandidates(await api.candidates());
      setImporting(true);
    } catch (e) {
      notify(String(e));
    }
  }
  async function importPath(path: string) {
    setBusy(path);
    try {
      const r = await api.importRun(path);
      onRefresh();
      setImporting(false);
      onOpen(r.id);
      notify("Recorded run imported without changing its source files");
    } catch (e) {
      notify(String(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="workspace-panel library-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR ORBITAL ARCHIVE</span>
          <h1>Every mission. Preserved.</h1>
          <p>
            Revisit the evidence, replay a handover, or put two policies side by
            side.
          </p>
        </div>
        <button className="primary-button" onClick={imports}>
          <FolderOpen size={15} />
          Import past run
        </button>
      </div>
      <div className="library-tools">
        <div className="search">
          <Search size={15} />
          <input
            aria-label="Search runs"
            placeholder="Search missions, policies or run IDs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          aria-label="Filter run status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {[
            "all",
            "completed",
            "running",
            "paused",
            "failed",
            "cancelled",
            "interrupted",
          ].map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All statuses" : s}
            </option>
          ))}
        </select>
        <button
          className="secondary-button"
          onClick={() => file.current?.click()}
        >
          <Upload size={14} />
          Import bundle
        </button>
        <button
          className="secondary-button"
          disabled={selected.length !== 2}
          onClick={onCompare}
        >
          <GitCompareArrows size={15} />
          Compare {selected.length ? `(${selected.length}/2)` : ""}
        </button>
      </div>
      <input
        type="file"
        hidden
        ref={file}
        accept=".json"
        onChange={async (e) => {
          const f = e.target.files?.[0];
          if (f)
            try {
              const r = await api.importBundle(
                JSON.parse(await f.text()) as Replay,
              );
              onRefresh();
              onOpen(r.id);
            } catch (e) {
              notify(String(e));
            }
          e.target.value = "";
        }}
      />
      <div className="run-table">
        <div className="lib-filters">
          <span className="lib-filter-label">POLICY</span>
          <select
            className="lib-filter-select"
            aria-label="Filter by policy"
            value={filterPolicy}
            onChange={(e) => setFilterPolicy(e.target.value)}
          >
            <option value="all">all</option>
            {policyOptions.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <span className="lib-filter-label">SCENARIO</span>
          <select
            className="lib-filter-select"
            aria-label="Filter by scenario"
            value={filterScenario}
            onChange={(e) => setFilterScenario(e.target.value)}
          >
            <option value="all">all</option>
            {scenarioOptions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <span style={{ marginLeft: "auto", fontSize: "9px", color: "var(--muted)" }}>
            {filtered.length} runs
          </span>
        </div>
        <div className="run-table-head">
          <span />
          <span>MISSION / RUN ID</span>
          <span>POLICY</span>
          <span>DELIVERY</span>
          <span>STATUS</span>
          <span />
        </div>
        {filtered.length ? (
          filtered.map((r, i) => (
            <div className="run-row" key={r.id}>
              <button
                className={`check-button ${selected.includes(r.id) ? "checked" : ""}`}
                aria-label={`Compare ${r.name}`}
                aria-pressed={selected.includes(r.id)}
                onClick={() => onToggle(r.id)}
              >
                {selected.includes(r.id) && <Check size={12} />}
              </button>
              <button className="run-title" onClick={() => onOpen(r.id)}>
                <span className="run-icon">
                  <Clock3 size={17} />
                </span>
                <span>
                  <b>{r.name}</b>
                  <small>
                    {r.id.startsWith("demo-")
                      ? "BUNDLED VERIFIED RUN"
                      : r.id.slice(0, 12).toUpperCase()}{" "}
                    <i /> {r.duration_s.toFixed(1)} s episode
                  </small>
                  <div className="run-headline-metrics">
                    {r.metrics?.delivery_ratio != null && (
                      <span className={`run-metric-chip ${r.metrics.delivery_ratio > 0.9 ? "good" : r.metrics.delivery_ratio < 0.6 ? "warn" : ""}`}>
                        {(r.metrics.delivery_ratio * 100).toFixed(0)}% delivery
                      </span>
                    )}
                    {r.metrics?.delay_p95_s != null && (
                      <span className={`run-metric-chip ${r.metrics.delay_p95_s < 0.08 ? "good" : r.metrics.delay_p95_s > 0.15 ? "warn" : ""}`}>
                        {(r.metrics.delay_p95_s * 1000).toFixed(0)} ms p95
                      </span>
                    )}
                    {r.metrics?.goodput_bps != null && (
                      <span className="run-metric-chip">
                        {(r.metrics.goodput_bps / 1e6).toFixed(2)} Mbps
                      </span>
                    )}
                  </div>
                </span>
              </button>
              <span className="policy-name">
                {r.policy.replaceAll("_", " ")}
              </span>
              <span className="delivery-cell">
                {format.percent(r.metrics?.delivery_ratio)}
                <small>{format.number(r.metrics?.delivered)} datagrams</small>
              </span>
              <span className={`status-chip ${r.status}`}>
                <i />
                {r.status}
              </span>
              <div className="row-actions">
                <button
                  className="icon-button"
                  title="Duplicate configuration"
                  aria-label={`Duplicate ${r.name}`}
                  onClick={() => onDuplicate(r.id)}
                >
                  <Copy size={14} />
                </button>
                {!r.id.startsWith("demo-") && (
                  <a
                    className="icon-button"
                    href={`/api/v1/runs/${r.id}/export`}
                    download
                    title="Export replay bundle"
                  >
                    <ArrowDownToLine size={14} />
                  </a>
                )}
                <button
                  className="icon-button"
                  aria-label={`Open ${r.name}`}
                  onClick={() => onOpen(r.id)}
                >
                  <ArrowUpRight size={15} />
                </button>
              </div>
              <span className="row-index">
                {String(i + 1).padStart(2, "0")}
              </span>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <Search size={28} />
            <h3>No matching missions</h3>
            <p>Try another filter or launch your first simulation.</p>
          </div>
        )}
      </div>
      <div className="library-foot">
        <span>
          <i className="status-dot" />
          Original run artifacts remain immutable.
        </span>
        <span>{filtered.length} missions in view</span>
      </div>
      {importing && (
        <div className="modal-backdrop" onClick={() => setImporting(false)}>
          <div
            className="modal import-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Import recorded run"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              onClick={() => setImporting(false)}
              aria-label="Close import"
            >
              <X size={18} />
            </button>
            <span className="eyebrow">EXISTING SIMULATION ARTIFACTS</span>
            <h2>Bring a mission into view.</h2>
            <p>
              Choose a recorded packet run from the repository. Originals stay
              untouched. Preparing geometry can take a moment.
            </p>
            <div className="candidate-list">
              {candidates.map((c) => (
                <button
                  key={c.path}
                  disabled={!!busy}
                  onClick={() => importPath(c.path)}
                >
                  <FolderOpen size={16} />
                  <span>
                    {c.name}
                    <small>{c.path}</small>
                  </span>
                  <span>
                    {busy === c.path ? (
                      "Importing…"
                    ) : (
                      <ArrowUpRight size={16} />
                    )}
                  </span>
                </button>
              ))}
              {!candidates.length && (
                <p>No completed packet runs found under runs/.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
