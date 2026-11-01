// Offline assets, reduced motion, presentation, WebGL fallback and future policy contract.
import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const base = process.env.LEO_TEST_URL ?? "http://127.0.0.1:5173";
const launch = (extra) =>
  chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    headless: true,
    args: [
      "--no-sandbox",
      "--enable-unsafe-swiftshader",
      "--use-angle=swiftshader",
      ...extra,
    ],
  });
const browser = await launch([]);
try {
  const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      reducedMotion: "reduce",
    }),
    page = await context.newPage(),
    external = [],
    errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== new URL(base).origin) {
      external.push(url.href);
      return route.abort();
    }
    if (url.pathname.startsWith("/api/"))
      return route.fulfill({
        status: 503,
        body: "Local API deliberately offline for compatibility test",
      });
    return route.continue();
  });
  await page.goto(base);
  await expect(
    page.getByRole("heading", { name: "Mission control." }),
  ).toBeVisible();
  await expect(page.getByText("OFFLINE REPLAY", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Play playback", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(1500);
  const cursor = await page.getByLabel("Simulation timeline").inputValue();
  await page.waitForTimeout(1000);
  expect(await page.getByLabel("Simulation timeline").inputValue()).toBe(
    cursor,
  );
  await page
    .getByRole("button", { name: "Bookmark current time", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /Jump to Saved bookmark/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Presentation mode", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Exit presentation", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/apogee-presentation.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  for (const [width, height] of [
    [1366, 768],
    [1440, 900],
    [1920, 1080],
    [390, 844],
  ]) {
    await page.setViewportSize({ width, height });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
    ).toBe(false);
  }
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
  console.log(
    "Offline assets, reduced motion, bookmarks, presentation and four responsive viewports passed",
  );
  await context.close();
  // Advertise a test-only future adapter and verify the existing launch UI forwards its checkpoint.
  const future = await browser.newContext({ reducedMotion: "reduce" }),
    p = await future.newPage();
  const caps = JSON.parse(
    await fs.readFile(
      new URL("../public/data/demo.json", import.meta.url),
      "utf8",
    ),
  );
  let launched;
  await p.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities"))
      return route.fulfill({
        json: {
          version: "test",
          engine_available: true,
          training_available: false,
          policies: [
            {
              id: "contract-adapter",
              label: "Contract adapter (test only)",
              kind: "learned",
              available: true,
              checkpoint_required: true,
              observation_version: 1,
              action_version: 1,
            },
          ],
        },
      });
    if (path.endsWith("/runs") && route.request().method() === "POST") {
      launched = route.request().postDataJSON();
      return route.fulfill({
        status: 422,
        json: {
          detail: "Test adapter inspected the manifest; no model was executed.",
        },
      });
    }
    return route.fulfill({
      json: path.endsWith("/scenarios")
        ? [{ id: "normal", name: "Normal", scenario: caps.scenario }]
        : [],
    });
  });
  await p.goto(base);
  await expect(
    p.getByRole("heading", { name: "Mission control." }),
  ).toBeVisible();
  await p.getByRole("button", { name: "New simulation", exact: true }).click();
  await p.getByLabel("Routing policy").selectOption("contract-adapter");
  await expect(
    p
      .getByRole("dialog")
      .getByRole("button", { name: "Launch simulation", exact: true }),
  ).toBeDisabled();
  await p
    .getByLabel("Checkpoint manifest ID")
    .fill("test-compatible-checkpoint");
  await p
    .getByRole("dialog")
    .getByRole("button", { name: "Launch simulation", exact: true })
    .click();
  await expect
    .poll(() => launched?.checkpoint_id)
    .toBe("test-compatible-checkpoint");
  expect(launched.policy).toBe("contract-adapter");
  console.log(
    "Future learned-policy launch contract passed without executing or claiming ML",
  );
  await future.close();
} finally {
  await browser.close();
}
const fallback = await launch(["--disable-webgl", "--disable-webgl2"]);
try {
  const p = await fallback.newPage({ reducedMotion: "reduce" });
  await p.goto(base);
  await expect(
    p.getByRole("img", { name: "Two-dimensional satellite map" }),
  ).toBeVisible({ timeout: 20000 });
  console.log("Automatic WebGL failure fallback passed");
} finally {
  await fallback.close();
}
