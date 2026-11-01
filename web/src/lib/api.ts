import type { Capabilities, Replay, RunRecord, Scenario } from "./types";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const value = await response.json();
      message =
        typeof value.detail === "string"
          ? value.detail
          : JSON.stringify(value.detail ?? value.error ?? value);
    } catch {
      /* use status */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
export const api = {
  capabilities: () => request<Capabilities>("/capabilities"),
  runs: () => request<RunRecord[]>("/runs"),
  run: (id: string) =>
    request<RunRecord & { scenario: Scenario }>(`/runs/${id}`),
  replay: (id: string) => request<Replay>(`/runs/${id}/replay`),
  window: (id: string, time: number) =>
    request<Replay>(`/runs/${id}/replay?center_s=${time}`),
  preview: (scenario: Scenario, signal?: AbortSignal) =>
    request<Replay>("/previews", {
      method: "POST",
      body: JSON.stringify({ scenario }),
      signal,
    }),
  launch: (
    scenario: Scenario,
    policy: string,
    name: string,
    checkpoint_id?: string,
  ) =>
    request<RunRecord>("/runs", {
      method: "POST",
      body: JSON.stringify({ scenario, policy, name, checkpoint_id }),
    }),
  command: (id: string, command: string) =>
    request<RunRecord>(`/runs/${id}/commands`, {
      method: "POST",
      body: JSON.stringify({ command }),
    }),
  presets: () =>
    request<{ id: string; name: string; scenario: Scenario }[]>("/scenarios"),
  saveScenario: (scenario: Scenario, name: string) =>
    request<{ id: string }>("/scenarios", {
      method: "POST",
      body: JSON.stringify({ scenario, name }),
    }),
  candidates: () =>
    request<{ path: string; name: string }[]>("/imports/candidates"),
  importRun: (path: string) =>
    request<RunRecord>("/imports", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  importBundle: (bundle: Replay) =>
    request<RunRecord>("/imports", {
      method: "POST",
      body: JSON.stringify({ bundle }),
    }),
};
export function download(data: unknown, filename: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
