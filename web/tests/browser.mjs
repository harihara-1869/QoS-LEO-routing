import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  headless: true,
  args: [
    "--no-sandbox",
    "--enable-unsafe-swiftshader",
    "--use-angle=swiftshader",
  ],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
let errors = [];
page.on("pageerror", (e) => {
  errors.push(String(e));
  console.log("PAGEERROR", String(e));
});
await page.goto(process.env.LEO_TEST_URL ?? "http://127.0.0.1:5173");
await expect(
  page.getByRole("heading", { name: "Mission control." }),
).toBeVisible();
await page.waitForTimeout(2500);
if (
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .count()
)
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .click();
await page.getByRole("button", { name: "Toggle camera rotation" }).click();
await page.screenshot({ path: "/tmp/apogee-desktop.png", fullPage: true });
await page.getByRole("button", { name: "Toggle 2D map" }).click();
await expect(
  page.getByRole("img", { name: "Two-dimensional satellite map" }),
).toBeVisible();
await page.getByRole("button", { name: "Toggle 2D map" }).click();
await page
  .getByRole("button", { name: "Constellation studio", exact: true })
  .click();
await expect(
  page.getByRole("heading", { name: "Build your orbit." }),
).toBeVisible();
await page.getByLabel("Altitude", { exact: true }).fill("570");
await expect(page.getByLabel("Altitude", { exact: true })).toHaveValue("570");
await page.getByRole("button", { name: "Ground", exact: true }).click();
await page
  .getByRole("button", { name: "Add ground station", exact: true })
  .click();
await expect(page.getByLabel("Station 5 name")).toBeVisible();
const previewResponse = page.waitForResponse((r) =>
  r.url().endsWith("/api/v1/previews"),
);
await page
  .getByRole("button", { name: "Generate preview", exact: true })
  .click();
const preview = await (await previewResponse).json();
expect(preview.capabilities.metrics).toBe(false);
expect(preview.nodes).toHaveLength(205);
expect(preview.scenario.constellation.altitude_km).toBe(570);
expect(preview.frames.every((f) => f.metrics === null)).toBe(true);
await page.screenshot({ path: "/tmp/apogee-studio.png", fullPage: true });
await page.getByRole("button", { name: "Policy lab", exact: true }).click();
await expect(
  page.getByRole("heading", { name: "A place for learned intelligence." }),
).toBeVisible();
await expect(page.locator(".policy-card")).toHaveCount(6);
await page.getByRole("button", { name: "Run library", exact: true }).click();
await expect(
  page.getByRole("heading", { name: "Every mission. Preserved." }),
).toBeVisible();
await page.getByLabel("Search runs").fill("nothing-matches");
await expect(page.getByText("No matching missions")).toBeVisible();
await page.getByLabel("Search runs").fill("");
await page.getByRole("button", { name: "Import bundle", exact: true }).click();
await page
  .locator("input[type=file]")
  .setInputFiles(
    fileURLToPath(new URL("../public/data/demo.json", import.meta.url)),
  );
await expect(
  page.getByRole("heading", { name: "Mission control." }),
).toBeVisible({ timeout: 30000 });
await page.waitForTimeout(1000);
await page.getByRole("button", { name: "Run library", exact: true }).click();
console.log("run rows", await page.locator(".run-row").count());
const checks = page.locator(".check-button");
await checks.nth(0).click();
await checks.nth(1).click();
await page.getByRole("button", { name: "Compare (2/2)", exact: true }).click();
await expect(
  page.getByRole("heading", { name: "Compare missions." }),
).toBeVisible();
await expect(page.getByText("Matched scenario", { exact: true })).toBeVisible();
await page.screenshot({ path: "/tmp/apogee-compare.png", fullPage: true });
await page.setViewportSize({ width: 390, height: 844 });
await page.getByRole("button", { name: "Open navigation" }).click();
await page
  .getByRole("button", { name: "Mission control", exact: true })
  .click();
await page.screenshot({ path: "/tmp/apogee-mobile.png", fullPage: true });
console.log(
  "mobile overflow",
  await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
);
expect(errors).toEqual([]);
expect(
  await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
).toBe(false);
console.log("ERRORS", errors);
await browser.close();
