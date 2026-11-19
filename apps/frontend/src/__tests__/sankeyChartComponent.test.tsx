import { render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as F from "./helpers/packageTestFixtures";

const state = vi.hoisted(() => ({ props: null as { option?: unknown; notMerge?: boolean; style?: unknown } | null, loading: null as ReactNode, cb: null as ((m: MutationRecord[]) => void) | null }));
vi.mock("next/dynamic", () => ({ default: (loader: () => Promise<unknown>, opts?: { loading?: () => ReactNode }) => { state.loading = opts?.loading?.() ?? null; void loader(); return function MockChart(p: { option: unknown; notMerge?: boolean; style: unknown }) { state.props = p; return <div data-testid="mock-echarts" />; }; } }));
import { SankeyChart } from "@/components/charts/SankeyChart";

describe("SankeyChart", () => {
  const colors: Record<string, string> = { ...F.SANKEY_DEFAULT_COLORS };
  beforeEach(() => { state.props = null; state.cb = null; F.stubSankeyGlobals(colors, (cb) => { state.cb = cb; }); });

  it("AC16.21.7 AC8.13.92 renders empty-state option and dynamic loading fallback", () => {
    render(<SankeyChart title="Cash Flow" height={320} />);
    F.assertSankeyEmpty(state.props, state.loading);
    render(<>{state.loading}</>); expect(F.txt("Loading chart...")).toBeInTheDocument();
  });

  it("AC16.21.7 / test_AC8_13_48 builds nodes, links, labels, and tooltips", () => {
    render(<SankeyChart {...F.SANKEY_DETAIL_DATA} />);
    F.assertSankeyDetail(state.props as { option?: Record<string, unknown>; notMerge?: boolean } | null);
  });

  it("AC16.21.8 recomputes theme colors on root attribute change", async () => {
    render(<SankeyChart operating={[{ category: "operating", subcategory: "Sales", amount: "100" }]} financing={[{ category: "financing", subcategory: "Loan", amount: "-20" }]} />);
    const col = (k: string) => (state.props?.option as F.SankeyOpt).series[0].data.find((n) => n.name === k)?.itemStyle?.color;
    expect(col("Operating-Inflows")).toBe("#1f9d55");
    colors["--success"] = "#00ff99"; colors["--foreground-muted"] = "#334155";
    state.cb?.([{ attributeName: "class" } as MutationRecord]);
    await waitFor(() => { expect(col("Operating-Inflows")).toBe("#00ff99"); expect(col("Operating-Sales")).toBe("#334155"); });
  });

  it("deduplicates subcategories safely for ECharts and separator substrings", async () => {
    render(<SankeyChart {...F.SANKEY_DUP_DATA} />);
    await F.assertSankeyDedup(state.props?.option as F.SankeyOpt);
    render(<SankeyChart {...F.SANKEY_SEP_DATA} />);
    expect((state.props?.option as F.SankeyOpt).series[0].links.find((l) => l.source === "Operating-Inflows" && l.target === "Operating-Alpha -> Beta")?.value).toBe(200);
  });
}); // AC-reporting.fe-report-surfaces.21 AC-reporting.fe-report-surfaces.22
