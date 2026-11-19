import { render as R, screen as S, waitFor as W, within } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { StatementCockpit } from "@/components/reports/ReportShell";
import { readReportFilters } from "@/hooks/useReportFilters";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation), Q1 = readReportFilters(new URLSearchParams("period=1Q&end=2026-03-31"), new Date(2026, 9, 22));

describe("StatementCockpit", () => {
  beforeEach(() => { api.mockReset(); X.mockApiMap(api, X.COCKPIT_DEFAULT_ROUTES); });

  it("deep-links, metrics, All reload", async () => {
    const { rerender } = R(<StatementCockpit filters={Q1} />); await X.checkCockpitDeepLinks();
    api.mockClear();
    rerender(<StatementCockpit filters={readReportFilters(new URLSearchParams("period=All&end=2026-03-31"), new Date(2026, 9, 22))} />);
    await W(() => E(S.getByText("Change in period").nextElementSibling).toHaveTextContent("—"));
    E(X.opCalls(api, X.OPS.BS)).toEqual([]);
  });

  it("switches, drills lineage, links valuations", async () => {
    const v1 = R(<StatementCockpit filters={Q1} />); await X.runCockpitDrillFlow(api); v1.unmount();
    X.mockApiMap(api, X.COCKPIT_VAL_ROUTES); R(<StatementCockpit filters={Q1} />);
    E(await S.findByRole("link", { name: "View valuation evidence for Valuation: CPF" })).toHaveAttribute("href", "/portfolio?panel=evidence");
  });

  it("empty switcher & retry", async () => {
    X.mockApiMap(api, X.COCKPIT_EMPTY_ROUTES);
    const v1 = R(<StatementCockpit filters={Q1} />);
    await W(() => E(X.metricEl("cockpit-card-balance-sheet", "Total assets")).toHaveTextContent("SGD 0"));
    E(S.queryByRole("tablist", { name: "Statement switcher" })).toBeNull(); v1.unmount();

    let fail = true;
    X.mockApiMap(api, { [X.OPS.BS]: X.makeCockpitBs("2026-03-31", "40000"), [X.OPS.IS]: () => (fail ? Promise.reject(new Error("income down")) : X.makeIncomeStatement()), [X.OPS.CF]: () => new Promise(() => undefined) });
    R(<StatementCockpit filters={Q1} />);
    E((await S.findByText("Statements unavailable: income down")).closest("[role='alert']")).not.toBeNull();
    E(within(S.getByTestId("cockpit-card-cash-flow")).getByRole("status")).toHaveTextContent("Loading…");
    fail = false; X.clkBtn("Retry"); await W(() => X.noTxt(/Statements unavailable/));
  });
});
