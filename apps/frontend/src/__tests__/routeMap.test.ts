import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

import { getPathMatch } from "next/dist/shared/lib/router/utils/path-match"
import { prepareDestination } from "next/dist/shared/lib/router/utils/prepare-destination"

import nextConfig from "../../next.config.mjs"
import {
  advancedItems,
  auditHubItems,
  bottomTabItems,
  moreItems,
} from "@/components/navigation"
import routeMapJson from "@/lib/route-map.json"

type RouteState = "target" | "shell" | "redirect"
interface RouteEntry {
  path: string
  state: RouteState
  into?: string
}

const routeMap = routeMapJson as { target_page_count: number; routes: RouteEntry[] }
const routes = routeMap.routes
const byPath = new Map(routes.map((r) => [r.path, r]))

const APP_DIR = path.resolve(__dirname, "../app")
const FLOWS_PATH = path.resolve(__dirname, "../../../../common/meta/flows/thirty_flows_ssot.json")

function discoverPageRoutes(dir: string, segments: string[] = []): string[] {
  const found: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const isGroup = entry.name.startsWith("(") && entry.name.endsWith(")")
      found.push(...discoverPageRoutes(path.join(dir, entry.name), isGroup ? segments : [...segments, entry.name]))
    } else if (entry.name === "page.tsx") {
      found.push("/" + segments.join("/"))
    }
  }
  return found
}

const stripQuery = (href: string) => href.split("?")[0]

// Resolve a URL with the Next.js matcher: the first redirect that matches wins.
async function resolveRedirect(url: string) {
  const parsed = new URL(url, "http://app.test")
  const query = Object.fromEntries(parsed.searchParams)
  for (const rule of (await nextConfig.redirects?.()) ?? []) {
    const params = getPathMatch(rule.source, { strict: true, removeUnnamedParams: true })(parsed.pathname)
    if (!params) continue
    const { parsedDestination } = prepareDestination({ appendParamsToQuery: false, destination: rule.destination, params, query })
    return { pathname: parsedDestination.pathname, query: { ...parsedDestination.query } }
  }
  return null
}

describe("route map (single source of truth for routes)", () => {
  // AC-meta.fe-ia-nav.31
  it("AC-meta.fe-ia-nav.31 lists each app page exactly once and gives redirect entries no page", () => {
    const pages = discoverPageRoutes(APP_DIR).sort()
    expect(pages.length).toBeGreaterThan(0)

    const paths = routes.map((r) => r.path)
    expect(new Set(paths).size, "duplicate path in route-map.json").toBe(paths.length)

    const withPage = routes.filter((r) => r.state !== "redirect").map((r) => r.path).sort()
    expect(withPage).toEqual(pages)
    for (const r of routes.filter((x) => x.state === "redirect")) {
      expect(pages, `${r.path} is a redirect and must have no page.tsx`).not.toContain(r.path)
    }
  })

  // AC-meta.fe-ia-nav.32
  it("AC-meta.fe-ia-nav.32 keeps exactly the target page count, only known states and keys, and sends every redirect to a live page", () => {
    const targets = routes.filter((r) => r.state === "target")
    expect(targets.length).toBe(routeMap.target_page_count)

    for (const r of routes) {
      expect(["target", "shell", "redirect"], `${r.path} has the unknown state ${r.state}`).toContain(r.state)
      expect(
        Object.keys(r).filter((key) => !["path", "state", "into"].includes(key)),
        `${r.path} has a key other than path, state and into`,
      ).toEqual([])
    }
    for (const r of routes.filter((x) => x.state === "redirect")) {
      const dest = byPath.get(stripQuery(r.into ?? ""))
      expect(dest, `${r.path} redirects to an unknown path ${r.into}`).toBeDefined()
      expect(dest?.state, `${r.path} must not redirect into another redirect`).not.toBe("redirect")
    }
  })

  // AC-meta.fe-ia-nav.33
  it("AC-meta.fe-ia-nav.33 makes next.config redirects equal the redirect entries", async () => {
    const toNext = (p: string) => p.replace(/\[([^\]]+)\]/g, ":$1")
    const expected = routes
      .filter((r) => r.state === "redirect")
      .map((r) => `${toNext(r.path)} -> ${toNext(r.into ?? "")} permanent`)
      .sort()
    const actual = ((await nextConfig.redirects?.()) ?? [])
      .map((r: { source: string; destination: string; permanent?: boolean }) =>
        `${r.source} -> ${r.destination} ${r.permanent ? "permanent" : "temporary"}`,
      )
      .sort()
    expect(expected.length).toBeGreaterThan(0)
    expect(actual).toEqual(expected)
  })

  // AC-meta.fe-ia-nav.35
  it("AC-meta.fe-ia-nav.35 redirects the upload-chain routes and keeps the legacy aliases off the retired notifications path", async () => {
    const expected: Record<string, string> = {
      "/notifications": "/upload",
      "/processing": "/upload",
      "/accounts/processing": "/upload",
      "/statements/[id]/review": "/statements/[id]",
      "/events": "/upload",
      "/review": "/upload",
    }
    const toNext = (p: string) => p.replace(/\[([^\]]+)\]/g, ":$1")
    const actual = new Map(
      ((await nextConfig.redirects?.()) ?? []).map((r: { source: string; destination: string }) => [r.source, r.destination]),
    )
    for (const [from, into] of Object.entries(expected)) {
      expect(byPath.get(from)?.state, `${from} must be a redirect entry`).toBe("redirect")
      expect(byPath.get(from)?.into, `${from} must redirect into ${into}`).toBe(into)
      expect(actual.get(toNext(from)), `next.config must redirect ${from}`).toBe(toNext(into))
    }
    expect(actual.get("/statements/:id/review")).toBe("/statements/:id")
  })

  // AC-meta.fe-ia-nav.34
  it("AC-meta.fe-ia-nav.34 points navigation links and the 30 flow UI surfaces only at paths that are not redirects", () => {
    const navHrefs = [...bottomTabItems, ...auditHubItems, ...moreItems, ...advancedItems].map((i) => i.href)
    expect(navHrefs.length).toBeGreaterThan(0)
    for (const href of navHrefs) {
      const entry = byPath.get(stripQuery(href))
      expect(entry, `nav href ${href} is not in route-map.json`).toBeDefined()
      expect(entry?.state, `nav href ${href} is a redirect`).not.toBe("redirect")
    }

    const flows = JSON.parse(fs.readFileSync(FLOWS_PATH, "utf-8")) as {
      domains: { flows: { id: number; ui_surface: string }[] }[]
    }
    const surfaces = flows.domains.flatMap((d) => d.flows)
    expect(surfaces.length).toBe(30)
    for (const flow of surfaces) {
      const normalized = stripQuery(flow.ui_surface).replace(/\{(\w+)\}/g, "[$1]")
      const entry = byPath.get(normalized)
      expect(entry, `flow #${flow.id} ui_surface ${flow.ui_surface} is not in route-map.json`).toBeDefined()
      expect(entry?.state, `flow #${flow.id} ui_surface ${flow.ui_surface} is a redirect`).not.toBe("redirect")
    }
  })

  // AC-meta.fe-audit-queue.1
  it("AC-meta.fe-audit-queue.1 redirects each old audit-queue route to the Needs you tab of /audit and keeps the run id", async () => {
    const redirects = (await nextConfig.redirects?.()) ?? []
    const destinationOf = (source: string) =>
      redirects.find((r: { source: string }) => r.source === source)?.destination
    expect(destinationOf("/attention")).toBe("/audit?tab=needs-you")
    expect(destinationOf("/confidence")).toBe("/audit?tab=needs-you")
    expect(destinationOf("/review/ai-suggestions")).toBe("/audit?tab=needs-you")
    expect(destinationOf("/review/run/:runId")).toBe("/audit?run_id=:runId")

    const pages = discoverPageRoutes(APP_DIR)
    for (const oldRoute of ["/attention", "/confidence", "/review/ai-suggestions", "/review/run/[runId]"]) {
      expect(byPath.get(oldRoute)?.state, `${oldRoute} must be a redirect`).toBe("redirect")
      expect(pages, `${oldRoute} must have no page.tsx`).not.toContain(oldRoute)
    }
  })

  // AC-meta.fe-reports-tabs.1
  it("AC-meta.fe-reports-tabs.1 redirects each old report route to its /reports tab and keeps the query", async () => {
    const redirects = (await nextConfig.redirects?.()) ?? []
    const destinationOf = (source: string) =>
      redirects.find((r: { source: string }) => r.source === source)?.destination
    const pages = discoverPageRoutes(APP_DIR)
    for (const tab of ["balance-sheet", "income-statement", "cash-flow", "package"]) {
      const oldRoute = `/reports/${tab}`
      expect(destinationOf(oldRoute), `${oldRoute} must redirect to its tab`).toBe(`/reports?tab=${tab}`)
      expect(byPath.get(oldRoute)?.state, `${oldRoute} must be a redirect`).toBe("redirect")
      expect(pages, `${oldRoute} must have no page.tsx`).not.toContain(oldRoute)
    }
    // Next.js merges the request query into the destination query, so `?currency=USD` survives the redirect.
    expect(redirects.filter((r: { source: string }) => r.source.startsWith("/reports/"))).toHaveLength(4)
  })

  // AC-meta.fe-tab-routes.1
  it("AC-meta.fe-tab-routes.1 redirects each old reconciliation, portfolio and accounts route to a tab or a panel and keeps its query", async () => {
    const expected: [string, string, Record<string, string>][] = [
      ["/reconciliation/unmatched", "/reconciliation", { tab: "unmatched" }],
      ["/reconciliation/review-queue", "/reconciliation", { tab: "review-queue" }],
      ["/portfolio/prices", "/portfolio", { panel: "prices" }],
      ["/portfolio/evidence", "/portfolio", { panel: "evidence" }],
      ["/portfolio/AAPL", "/portfolio", { ticker: "AAPL" }],
      ["/accounts", "/settings", { tab: "accounts" }],
      [
        "/reconciliation/unmatched?statement_id=s1&return_to=%2Fstatements%2Fs1",
        "/reconciliation",
        { tab: "unmatched", statement_id: "s1", return_to: "/statements/s1" },
      ],
      ["/portfolio/evidence?source_class=property", "/portfolio", { panel: "evidence", source_class: "property" }],
    ]
    for (const [from, pathname, query] of expected) {
      expect(await resolveRedirect(from), `${from} must redirect to ${pathname} with ${JSON.stringify(query)}`).toEqual({
        pathname,
        query,
      })
    }

    const pages = discoverPageRoutes(APP_DIR)
    const oldRoutes = ["/reconciliation/unmatched", "/reconciliation/review-queue", "/portfolio/[ticker]", "/portfolio/prices", "/portfolio/evidence", "/accounts"]
    for (const oldRoute of oldRoutes) {
      expect(byPath.get(oldRoute)?.state, `${oldRoute} must be a redirect`).toBe("redirect")
      expect(pages, `${oldRoute} must have no page.tsx`).not.toContain(oldRoute)
    }
  })
})
