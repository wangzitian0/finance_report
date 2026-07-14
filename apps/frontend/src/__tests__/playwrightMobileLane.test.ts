// #1827 G-mobile-lane — contract lock on the Playwright project list.
//
// The EPIC-022 flagship IA is the mobile bottom-tab shell; this test locks
// the blocking Playwright job to a true mobile device project running the
// shell journeys. Red-team: delete the mobile project (or drop a journey
// from its testMatch) -> this vitest suite reds, so the mobile lane cannot
// silently disappear from CI.

import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import playwrightConfig, {
  MOBILE_LANE_SPECS,
  MOBILE_PROJECT_NAME,
} from "../../playwright.config";

const here = dirname(fileURLToPath(import.meta.url));
const playwrightDir = resolve(here, "../../playwright");

// Independent copy of the minimum shell-journey set (issue #1827). Deliberately
// NOT imported from the config: shrinking the config list below this floor
// must red here, not silently shrink both sides at once.
const REQUIRED_MOBILE_SPECS = [
  "attention-surface.spec.ts",
  "epic022-attention-journey.spec.ts",
  "epic022-bottom-tab-ia.spec.ts",
  "epic022-drilldown-journey.spec.ts",
  "epic022-ia-shell.spec.ts",
  "workflow-navigation.spec.ts",
];

type ProjectEntry = {
  name?: string;
  testMatch?: string | RegExp | (string | RegExp)[];
  use?: {
    isMobile?: boolean;
    hasTouch?: boolean;
    viewport?: { width: number; height: number } | null;
  };
};

function findProject(name: string): ProjectEntry | undefined {
  const projects = (playwrightConfig.projects ?? []) as ProjectEntry[];
  return projects.find((p) => p.name === name);
}

describe("playwright mobile viewport lane (#1827 G-mobile-lane)", () => {
  it("AC-testing.fe-lane.1 the blocking Playwright config declares a true mobile device project", () => {
    const mobile = findProject(MOBILE_PROJECT_NAME);
    expect(mobile, `project '${MOBILE_PROJECT_NAME}' must exist`).toBeDefined();
    // A true mobile profile, not a resized desktop: touch + mobile UA
    // semantics + a phone-width viewport.
    expect(mobile?.use?.isMobile).toBe(true);
    expect(mobile?.use?.hasTouch).toBe(true);
    const width = mobile?.use?.viewport?.width ?? Number.POSITIVE_INFINITY;
    expect(width).toBeLessThanOrEqual(500);
  });

  it("AC-testing.fe-lane.1 the mobile project runs every EPIC-022 shell journey", () => {
    const mobile = findProject(MOBILE_PROJECT_NAME);
    const testMatch = mobile?.testMatch;
    expect(Array.isArray(testMatch), "mobile project must use a testMatch list").toBe(true);
    const matched = (testMatch as (string | RegExp)[]).map((m) => String(m));
    for (const spec of REQUIRED_MOBILE_SPECS) {
      expect(matched, `mobile lane must include ${spec}`).toContain(spec);
    }
  });

  it("AC-testing.fe-lane.1 every mobile-lane spec file exists on disk", () => {
    // Guards renames: a journey renamed without updating the lane would
    // otherwise match nothing and pass vacuously.
    for (const spec of MOBILE_LANE_SPECS) {
      expect(
        existsSync(resolve(playwrightDir, spec)),
        `${spec} is declared in the mobile lane but missing on disk`,
      ).toBe(true);
    }
  });

  it("keeps the desktop chromium project alongside the mobile lane", () => {
    expect(findProject("chromium")).toBeDefined();
  });
});
