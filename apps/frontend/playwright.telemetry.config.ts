import { defineConfig, devices } from '@playwright/test';

/**
 * Dedicated Playwright config for the #1169 telemetry-emission E2E
 * (EPIC-024 AC24.2). It runs its OWN Next.js server with the browser-OTel and
 * OpenPanel config supplied via `webServer.env`, so the real root layout mounts
 * `<FrontendTelemetry>` + `<Analytics>` with active config — without forcing
 * telemetry on for every other E2E in the default `playwright.config.ts`.
 *
 * Hermetic: the configured OTLP collector + OpenPanel endpoints/script are
 * fakes intercepted in-test (no real SigNoz/OpenPanel is contacted). The values
 * below are read at REQUEST time by the `force-dynamic` server layout, so
 * passing them through `webServer.env` (rather than baking them into the build)
 * is sufficient.
 */
const PORT = process.env.TELEMETRY_E2E_PORT || '3210';
const BASE_URL = `http://127.0.0.1:${PORT}`;

// Fake, never-contacted endpoints — all SAME-ORIGIN as the app so the
// production CSP (`script-src 'self'`, `connect-src 'self'`) permits them. The
// spec intercepts these routes with `page.route`, so no real telemetry backend
// is hit (the paths need not exist on the server); we only assert that the
// browser tries to emit to them.
const TELEMETRY_ENV = {
  // Browser OTel → OTLP/HTTP collector. Read by the server layout and passed to
  // <FrontendTelemetry> as the `endpoint` prop.
  NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: `${BASE_URL}/v1/traces`,
  NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: 'e2e-telemetry',
  NEXT_PUBLIC_GIT_SHA: 'e2e-test-sha',
  // OpenPanel page-view analytics. Read by the server layout and passed to
  // <Analytics>. The script + api are stubbed in-test, also same-origin.
  OPENPANEL_CLIENT_ID: 'e2e-telemetry-client',
  OPENPANEL_API_URL: `${BASE_URL}/openpanel-api`,
  OPENPANEL_SCRIPT_URL: `${BASE_URL}/openpanel-op1.js`,
  OPENPANEL_ENVIRONMENT: 'e2e-telemetry',
  NEXT_PUBLIC_APP_URL: BASE_URL,
};

export default defineConfig({
  testDir: './playwright',
  testMatch: 'telemetry-emission.spec.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? 'line' : 'list',
  webServer: {
    command: process.env.CI
      ? `npm run start -- --port ${PORT}`
      : `npm run build && npm run start -- --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: TELEMETRY_ENV,
  },
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
