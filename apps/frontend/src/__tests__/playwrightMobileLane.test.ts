import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it, vi } from "vitest";
vi.mock("@playwright/test", () => ({ defineConfig: (c: any) => c, devices: { "Desktop Chrome": { userAgent: "d" }, "Pixel 7": { isMobile: true, hasTouch: true, viewport: { width: 412, height: 915 } } } }));
import pw, { buildPlaywrightConfig, MOBILE_LANE_SPECS, MOBILE_PROJECT_NAME } from "../../playwright.config";
const dir = resolve(__dirname, "../../playwright"), proj = (n: string) => (pw.projects as any[])?.find((p) => p.name === n), E = expect;
it("AC-testing.fe-lane.1 #2669 mobile lane & config", () => {
const m = proj(MOBILE_PROJECT_NAME);
E(m?.use).toMatchObject({ isMobile: true, hasTouch: true });
E(m?.use?.viewport?.width ?? Infinity).toBeLessThanOrEqual(500);
E(Array.isArray(m?.testMatch)).toBe(true);
  const matched = (m.testMatch as unknown[]).map(String);
  E(matched).toEqual(["ui-visual-smoke.spec.ts"]);
  for (const s of MOBILE_LANE_SPECS) E(existsSync(resolve(dir, s)), s).toBe(true);
E(proj("chromium")).toBeDefined();
for (const [env, reuse, port, build] of [[{}, false, 3000, true], [{ PW_REUSE_SERVER: "1" }, true, 3000, true], [{ PORT: "3456" }, false, 3456, true], [{ CI: "true", PORT: "3456" }, false, 3456, false]] as const) {
const cfg = buildPlaywrightConfig(env as Record<string, string>), url = `http://127.0.0.1:${port}`, command = `${build ? "npm run build && " : ""}npm run start -- --port ${port}`;
E(cfg.webServer).toMatchObject({ reuseExistingServer: reuse, url, command });
E(cfg.use?.baseURL).toBe(url);
}
});
