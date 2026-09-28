import { defineConfig, devices } from "@playwright/test";

// The suite runs its own backend and frontend on separate ports against a dedicated,
// freshly reset database, so it never touches dev servers (:3000/:8000) or dev data.
const WEB_PORT = 3001;
const API_PORT = 8001;
const BASE_URL = `http://localhost:${WEB_PORT}`;
const API_ORIGIN = `http://localhost:${API_PORT}`;
const E2E_DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? "postgresql+asyncpg://opspilot:opspilot@localhost:5432/opspilot_e2e";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true, // every test creates its own organization
  forbidOnly: !!process.env.CI,
  retries: 0, // a flaky test is a bug to fix, not to retry away
  workers: process.env.CI ? 2 : 4,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run python -m scripts.reset_e2e_database && uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `${API_ORIGIN}/health`,
      env: {
        ...process.env,
        DATABASE_URL: E2E_DATABASE_URL,
        ALLOWED_ORIGINS: JSON.stringify([BASE_URL]),
      } as Record<string, string>,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run build && npx next start -p ${WEB_PORT}`,
      url: `${BASE_URL}/login`,
      env: { ...process.env, NEXT_DIST_DIR: ".next-e2e", API_ORIGIN } as Record<string, string>,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
