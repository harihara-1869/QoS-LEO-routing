// Real-engine integration smoke. Start the local API and Vite, then npm run test:live.
import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  headless: true,
  args: [
    "--no-sandbox",
    "--enable-unsafe-swiftshader",
    "--use-angle=swiftshader",
  ],
});
const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  }),
  errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const base = process.env.LEO_TEST_URL ?? "http://127.0.0.1:5173";
const get = async (id) =>
  (await page.request.get(`${base}/api/v1/runs/${id}`)).json();
try {
  await page.goto(base);
  await expect(
    page.getByRole("heading", { name: "Mission control." }),
  ).toBeVisible();
  const config = JSON.parse(
    await fs.readFile(
      new URL("../../scenarios/phase5/normal.json", import.meta.url),
      "utf8",
    ),
  );
  config.duration_s = 2;
  config.flows.forEach((f) => (f.end_time = 1.5));
  await page
    .getByRole("button", { name: "Constellation studio", exact: true })
    .click();
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  await page.getByLabel("Scenario JSON").fill(JSON.stringify(config));
  await page.getByRole("button", { name: "Apply JSON", exact: true }).click();
  await page
    .getByRole("button", { name: "Launch simulation", exact: true })
    .click();
  await page
    .getByLabel("Mission name")
    .fill("Browser integration · live engine");
  const accepted = page.waitForResponse(
    (r) => r.url().endsWith("/api/v1/runs") && r.request().method() === "POST",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Launch simulation", exact: true })
    .click();
  const record = await (await accepted).json();
  console.log("created", record.id);
  await page.getByRole("button", { name: "Pause engine", exact: true }).click();
  await expect
    .poll(async () => (await get(record.id)).status, { timeout: 90000 })
    .toBe("paused");
  await expect(
    page.getByRole("button", { name: "Resume engine", exact: true }),
  ).toBeVisible();
  const paused = await get(record.id);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Resume engine", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  expect((await get(record.id)).progress).toBe(paused.progress);
  console.log("engine paused + browser reconnected at", paused.progress);
  await page
    .getByRole("button", { name: "Resume engine", exact: true })
    .click();
  await page.getByRole("button", { name: "Pause view", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Catch up to live", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Catch up to live", exact: true })
    .click();
  await expect
    .poll(async () => (await get(record.id)).status, { timeout: 90000 })
    .toBe("completed");
  await expect(page.getByText("SAVED REPLAY", { exact: true })).toBeVisible({
    timeout: 10000,
  });
  const replay = await (
    await page.request.get(`${base}/api/v1/runs/${record.id}/replay`)
  ).json();
  expect(
    replay.frames.some(
      (f) => f.time_s > 0 && f.time_s < 2 && f.metrics.generated > 0,
    ),
  ).toBeTruthy();
  const final = replay.frames.at(-1).metrics;
  expect(final.generated).toBe(
    final.delivered + final.dropped + final.in_flight,
  );
  await page.screenshot({
    path: "/tmp/apogee-live-completed.png",
    fullPage: true,
  });
  console.log("real run completed", final);
  // Cancel a second owned job at a cooperative pause after simulation time advances.
  const second = structuredClone(config);
  second.duration_s = 5;
  second.flows.forEach((f) => (f.end_time = 4.5));
  const b = await (
    await page.request.post(`${base}/api/v1/runs`, {
      data: {
        scenario: second,
        policy: "predictive",
        name: "Browser integration · cancellation",
      },
    })
  ).json();
  await page.request.post(`${base}/api/v1/runs/${b.id}/commands`, {
    data: { command: "pause" },
  });
  await expect
    .poll(async () => (await get(b.id)).status, { timeout: 90000 })
    .toBe("paused");
  await page.request.post(`${base}/api/v1/runs/${b.id}/commands`, {
    data: { command: "resume" },
  });
  await expect
    .poll(async () => (await get(b.id)).progress, { timeout: 90000 })
    .toBeGreaterThan(0.05);
  await page.request.post(`${base}/api/v1/runs/${b.id}/commands`, {
    data: { command: "pause" },
  });
  await expect
    .poll(async () => (await get(b.id)).status, { timeout: 90000 })
    .toBe("paused");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Cancel simulation", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page
    .getByRole("button", { name: "Cancel simulation", exact: true })
    .click();
  await expect
    .poll(async () => (await get(b.id)).status, { timeout: 30000 })
    .toBe("cancelled");
  await page.reload();
  await page.getByRole("button", { name: "Run library", exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: "Open Browser integration · live engine",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Open Browser integration · cancellation",
      exact: true,
    }),
  ).toBeVisible();
  const partial = await (
    await page.request.get(`${base}/api/v1/runs/${b.id}/replay`)
  ).json();
  expect(partial.status).toBe("cancelled");
  expect(partial.duration_s).toBeLessThan(5);
  expect(partial.duration_s).toBeGreaterThan(0);
  expect(errors).toEqual([]);
  console.log("live/reconnect/view pause/cancel/history passed, no JS errors");
} finally {
  await browser.close();
}
