import { render as R, screen as S } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import { HomeActionBanner, pickHomeAction } from "@/components/home/HomeActionBanner";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("HomeActionBanner", () => {
  beforeEach(() => api.mockReset());

  it("counts & queue over blocker", async () => {
    X.mockApiMap(api, X.ACTION_BASE_ROUTES, null);
    const v1 = R(<HomeActionBanner />); await S.findByRole("region", { name: "Needs attention" });
    X.checkBannerCard("2 items need you", "Open Needs you", "/audit?tab=needs-you"); v1.unmount();

    X.mockApiMap(api, X.ACTION_CONFLICT_ROUTES, null);
    const v2 = R(<HomeActionBanner />); await S.findByRole("region", { name: "Needs attention" });
    X.checkBannerCard("3 items need you", "PayNow Transfer REF 4471", "/reconciliation?tab=unmatched&from=attention", "A blocker holds your reports"); v2.unmount();
  });

  it("silent, fallback, pickHomeAction", async () => {
    await X.runBannerSilentAndFallback(api, () => R(<HomeActionBanner />));
    X.checkPickHomeActionCases(pickHomeAction);
  });
});
// AC-reconciliation.fe-ia-reconciliation.4
