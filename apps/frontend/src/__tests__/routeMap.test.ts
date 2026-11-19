import fs from "fs";
import path from "path";
import { describe, expect as E, it } from "vitest";
import { getPathMatch } from "next/dist/shared/lib/router/utils/path-match";
import { prepareDestination } from "next/dist/shared/lib/router/utils/prepare-destination";
import nextConfig from "../../next.config.mjs";
import { advancedItems, auditHubItems, bottomTabItems, moreItems } from "@/components/navigation";
import routeMapJson from "@/lib/route-map.json";
import * as X from "./helpers/shellTestFixtures";

type R = { path: string; state: "target" | "shell" | "redirect"; into?: string };
const rm = routeMapJson as { target_page_count: number; routes: R[] }, routes = rm.routes;
const strip = (h: string) => h.split("?")[0], pages = X.discoverPageRoutes(path.resolve(__dirname, "../app")).sort();
const byPath = new Map(routes.map((r) => [r.path, r]));

describe("route map", () => {
  it("AC-meta.fe-ia-nav.31-32 pages, states, targets", () => { X.checkRouteMapIntegrity(routes, pages, rm.target_page_count); });

  it("AC-meta.fe-ia-nav.34 nav & 47 SSOT surfaces", () => {
    const nav = [...bottomTabItems, ...auditHubItems, ...moreItems, ...advancedItems].map((i) => i.href);
    E(nav.length).toBeGreaterThan(0); for (const h of nav) E(byPath.get(strip(h))?.state).not.toBe("redirect");
    const flows = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../../../common/meta/flows/user_cases_ssot.json"), "utf-8")) as { domains: { user_cases: { id: string; ui_surface: string }[] }[] };
    const s = flows.domains.flatMap((d) => d.user_cases); E(s).toHaveLength(47);
    for (const uc of s) { const e = byPath.get(strip(uc.ui_surface).replace(/\{(\w+)\}/g, "[$1]")); E(e, uc.id).toBeDefined(); E(e?.state, uc.id).not.toBe("redirect"); }
  });

  it("AC-meta.fe-ia-nav.33-35 & legacy redirects", async () => {
    await X.runRouteRedirectsCheck((await nextConfig.redirects?.()) ?? [], routes, pages, byPath, getPathMatch, prepareDestination);
  });
});
