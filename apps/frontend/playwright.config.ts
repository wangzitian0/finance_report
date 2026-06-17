import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './playwright',
  // The #1169 telemetry-emission spec (EPIC-024 AC24.2) needs the browser-OTel
  // and OpenPanel config injected via `webServer.env`; it runs under its own
  // `playwright.telemetry.config.ts` and would be a no-op (telemetry disabled)
  // under this default server, so it is excluded here.
  testIgnore: 'telemetry-emission.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  webServer: {
    command: process.env.CI ? 'npm run start' : 'npm run build && npm run start',
    url: process.env.NEXT_PUBLIC_APP_URL || 'http://127.0.0.1:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  use: {
    baseURL: process.env.NEXT_PUBLIC_APP_URL || 'http://127.0.0.1:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
