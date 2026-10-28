import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], channel: process.env.E2E_BROWSER_CHANNEL ?? "chrome", baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100" },
});
