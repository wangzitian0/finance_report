import { render as R } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import HomePage from "@/app/(main)/page";
import { apiOperation } from "@/lib/api";
import { setTestUrl, testUrl } from "./helpers/nextNavigation";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);
let start: string | null = "2026-07-01", latestEnd: string | null = null;

describe("Home coverage (#2646)", () => {
  beforeEach(() => { api.mockReset(); start = "2026-07-01"; latestEnd = null; setTestUrl("/?end=2026-10-22"); X.mockApiMap(api, X.makeCoverageRoutes(() => start, () => latestEnd)); });
  it("bounds default/All & disables Previous", () => X.runHomeCoverageBounds(api, () => R(<HomePage />), setTestUrl));
  it("unbounded 1Y & jump to latest", () => X.runHomeCoverageJump(() => R(<HomePage />), (s, l) => { start = s; latestEnd = l; }, setTestUrl, testUrl));
});
