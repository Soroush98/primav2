import { defineConfig, devices } from "@playwright/test";

// Smoke-level e2e: a stub backend (e2e/stub-backend.mjs) stands in for FastAPI so
// the run needs no GCP, Gemini, or torch. The Next app is built and started with
// BACKEND_URL pointed at the stub; the stub 401s unless the proxy attaches the
// expected X-API-Key, so a passing run also proves the server-side key wiring.
const FRONTEND_PORT = 3105;
const STUB_PORT = 4545;
const API_KEY = "e2e-stub-key";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `node e2e/stub-backend.mjs ${STUB_PORT} ${API_KEY}`,
      url: `http://127.0.0.1:${STUB_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
    },
    {
      // Serve the standalone bundle the same way the Dockerfile does (`next start`
      // doesn't support output: "standalone"), so e2e exercises the prod artifact.
      command:
        "npm run build" +
        " && rm -rf .next/standalone/public .next/standalone/.next/static" +
        " && cp -r public .next/standalone/public" +
        " && cp -r .next/static .next/standalone/.next/static" +
        " && node .next/standalone/server.js",
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        PORT: String(FRONTEND_PORT),
        HOSTNAME: "127.0.0.1",
        NEXT_TELEMETRY_DISABLED: "1",
        BACKEND_URL: `http://127.0.0.1:${STUB_PORT}`,
        BACKEND_API_KEY: API_KEY,
      },
    },
  ],
});
