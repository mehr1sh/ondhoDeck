import { defineConfig } from "@playwright/test";

/**
 * Browser end-to-end tests against an already running local stack (see docs/LOCAL_DEVELOPMENT.md):
 * API on :8000, auth gateway on :54331, Mailpit on :8025, worker running, and the frontend at E2E_BASE_URL.
 * The API's CORS_ORIGINS must include E2E_BASE_URL. Accounts and data are created fresh per run.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  outputDir: process.env.E2E_OUTPUT_DIR || "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    actionTimeout: 20_000,
  },
});
