import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

import nextConfig from "../../next.config.mjs"
import {
  advancedItems,
  auditHubItems,
  bottomTabItems,
  moreItems,
} from "@/components/navigation"
import routeMapJson from "@/lib/route-map.json"

type RouteState = "target" | "shell" | "merge" | "redirect"
interface RouteEntry {
  path: string
  state: RouteState
  into?: string
  lane?: string
}

const routeMap = routeMapJson as { target_page_count: number; routes: RouteEntry[] }
const routes = routeMap.routes
const byPath = new Map(routes.map((r) => [r.path, r]))
const LANES = ["LA", "LB", "LC", "LD"]

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
  it("AC-meta.fe-ia-nav.32 keeps exactly the target page count and sends every merge and redirect to a live page", () => {
    const targets = routes.filter((r) => r.state === "target")
    expect(targets.length).toBe(routeMap.target_page_count)

    for (const r of routes.filter((x) => x.state === "merge")) {
      expect(LANES, `${r.path} needs a lane in ${LANES.join(", ")}`).toContain(r.lane)
      expect(byPath.get(r.into ?? "")?.state, `${r.path} must merge into a target page`).toBe("target")
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
      const normalized = flow.ui_surface.replace(/\{(\w+)\}/g, "[$1]")
      const entry = byPath.get(normalized)
      expect(entry, `flow #${flow.id} ui_surface ${flow.ui_surface} is not in route-map.json`).toBeDefined()
      expect(entry?.state, `flow #${flow.id} ui_surface ${flow.ui_surface} is a redirect`).not.toBe("redirect")
    }
  })
})
