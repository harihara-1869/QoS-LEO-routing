import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Copy,
  FolderOpen,
  Search,
  Upload,
  GitCompareArrows,
} from "lucide-react";
import type { Replay, RunRecord } from "../lib/types";
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
    return () => {
      window.removeEventListener("keydown", close);
      previous?.focus();
    };
  }, [importing]);

  const policies = Array.from(new Set(runs.map((r) => r.policy)));

  const filtered = runs.filter((r) => {
    if (status !== "all" && r.status !== status) return false;
    if (filterPolicy !== "all" && r.policy !== filterPolicy) return false;
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      r.name.toLowerCase().includes(q) ||
      r.policy.toLowerCase().includes(q) ||
      r.id.toLowerCase().includes(q)
    );
  });

  async function imports() {
    try {
      const list = await api.candidates();
      setCandidates(list);
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
    <div className="view">
      <div className="title-row">
        <div>
          <h1>Every mission. Preserved.</h1>
          <p className="sub">
            Revisit the evidence, replay a handover, or put two policies side by side.
          </p>
        </div>
        <button className="btn pri" onClick={imports}>
          <Upload size={14} />
          Import past run
        </button>
      </div>

      <div className="tools">
        <input
          aria-label="Search runs"
          placeholder="Search missions, policies or run IDs"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label="Filter policy"
          value={filterPolicy}
          onChange={(e) => setFilterPolicy(e.target.value)}
        >
          <option value="all">All policies</option>
          {policies.map((p) => (
            <option key={p} value={p}>
              {p.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter run status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <button
          className="btn"
          disabled={selected.length !== 2}
          onClick={onCompare}
        >
          <GitCompareArrows size={14} />
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
        }}
      />

      <div className="card lib">
        <table>
          <thead>
            <tr>
              <th style={{ width: 44, textAlign: "center" }}></th>
              <th>Mission</th>
              <th>Results</th>
              <th>Policy</th>
              <th>Status</th>
              <th style={{ width: 110, textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length > 0 ? (
              filtered.map((r) => (
                <tr
                  key={r.id}
                  className={selected.includes(r.id) ? "selected" : ""}
                >
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      aria-label={`Select ${r.name}`}
                      checked={selected.includes(r.id)}
                      onChange={() => onToggle(r.id)}
                    />
                  </td>
                  <td>
                    <b
                      style={{ cursor: "pointer", display: "block" }}
                      onClick={() => onOpen(r.id)}
                    >
                      {r.name}
                    </b>
                    <small style={{ color: "var(--mute)", display: "block", fontSize: "12px" }}>
                      {r.duration_s != null
                        ? `${r.duration_s.toFixed(1)} s run`
                        : "Duration unavailable"}
                    </small>
                  </td>
                  <td>
                    {r.metrics?.delivery_ratio != null && (
                      <span className="chip">
                        {(r.metrics.delivery_ratio * 100).toFixed(0)}% delivery
                      </span>
                    )}
                    {r.metrics?.delay_p95_s != null && (
                      <span className="chip">
                        {(r.metrics.delay_p95_s * 1000).toFixed(0)} ms p95
                      </span>
                    )}
                    {r.metrics?.goodput_bps != null && (
                      <span className="chip">
                        {(r.metrics.goodput_bps / 1e6).toFixed(2)} Mbps
                      </span>
                    )}
                  </td>
                  <td style={{ textTransform: "capitalize" }}>
                    {r.policy.replaceAll("_", " ")}
                  </td>
                  <td>
                    <span className="ok">{r.status}</span>
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button
                      className="btn"
                      style={{ padding: "4px 8px", marginRight: "4px" }}
                      title="Duplicate"
                      onClick={() => onDuplicate(r.id)}
                    >
                      <Copy size={13} />
                    </button>
                    <button
                      className="btn"
                      style={{ padding: "4px 8px" }}
                      title="Open run"
                      onClick={() => onOpen(r.id)}
                    >
                      <ArrowUpRight size={13} />
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", padding: "40px 16px", color: "var(--mute)" }}>
                  <Search size={24} style={{ display: "block", margin: "0 auto 8px" }} />
                  No matching missions found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p style={{ color: "var(--mute)", fontSize: "13px", marginTop: "16px", display: "flex", alignItems: "center", gap: "8px" }}>
        <i className="dot" style={{ background: "var(--acc)", margin: 0 }} />
        Original run artifacts remain immutable. ({filtered.length} missions in view)
      </p>

      {importing && (
        <div className="modal-backdrop" onClick={() => setImporting(false)}>
          <div
            className="dialog-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Import recorded run"
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <h2 style={{ margin: 0 }}>Bring a mission into view</h2>
              <button
                className="tg"
                style={{ width: "32px", height: "32px", fontSize: "14px" }}
                onClick={() => setImporting(false)}
              >
                ✕
              </button>
            </div>
            <p className="sub" style={{ margin: "0 0 16px" }}>
              Choose a recorded packet run from the repository. Originals stay untouched.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "300px", overflowY: "auto" }}>
              {candidates.map((c) => (
                <button
                  key={c.path}
                  className="btn"
                  style={{ justifyContent: "space-between", textAlign: "left" }}
                  disabled={!!busy}
                  onClick={() => importPath(c.path)}
                >
                  <span>
                    <FolderOpen size={14} style={{ marginRight: "8px" }} />
                    <b>{c.name}</b>
                    <small style={{ display: "block", color: "var(--mute)" }}>{c.path}</small>
                  </span>
                  <span>{busy === c.path ? "Importing…" : "→"}</span>
                </button>
              ))}
              {!candidates.length && <p style={{ color: "var(--mute)" }}>No completed packet runs found under runs/.</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
