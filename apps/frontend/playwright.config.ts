import { defineConfig, devices } from '@playwright/test';

/**
 * Name of the mobile-viewport Playwright project (#1827 G-mobile-lane).
 *
 * The EPIC-022 flagship IA is the mobile bottom-tab shell, so the shell
 * journeys must run under a true mobile device profile (touch enabled,
 * mobile UA, narrow viewport) inside the blocking Playwright job — not
 * only under Desktop Chrome with a hand-resized viewport.
 */
export const MOBILE_PROJECT_NAME = 'mobile-chrome';

/**
 * The EPIC-022 shell journeys that MUST run under the mobile project.
 * Locked by src/__tests__/playwrightMobileLane.test.ts — removing the
 * project or dropping a journey from this list turns vitest red.
 */
export const MOBILE_LANE_SPECS = [
  'attention-surface.spec.ts',
  'epic022-attention-journey.spec.ts',
  'epic022-bottom-tab-ia.spec.ts',
  'epic022-drilldown-journey.spec.ts',
  'epic022-ia-shell.spec.ts',
  'mobile-ux.spec.ts',
  'workflow-navigation.spec.ts',
] as const;

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
    {
      // #1827 G-mobile-lane: true mobile device profile (touch, mobile UA,
      // 412px-wide viewport) for the EPIC-022 shell journeys. Runs on the
      // same chromium binary CI already installs.
      name: MOBILE_PROJECT_NAME,
      use: { ...devices['Pixel 7'] },
      testMatch: [...MOBILE_LANE_SPECS],
    },
  ],
});
