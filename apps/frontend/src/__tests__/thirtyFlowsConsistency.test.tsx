import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

interface FlowDefinition {
  id: number
  name: string
  title: string
  ui_surface: string
  component: string
  backend_endpoint: string
  invariant: string
  test_ref: string
  backend_test_ref: string
  frontend_test_ref: string
  domain_id?: number
  domain_name?: string
}

interface DomainDefinition {
  id: number
  name: string
  flows: FlowDefinition[]
}

interface SSoTRegistry {
  version: string
  description: string
  domains: DomainDefinition[]
}

function loadRegistry(): SSoTRegistry {
  const ssotPath = path.resolve(__dirname, "../../../../common/meta/flows/thirty_flows_ssot.json")
  if (!fs.existsSync(ssotPath)) {
    throw new Error(`SSOT registry file not found at ${ssotPath}`)
  }
  const raw = fs.readFileSync(ssotPath, "utf-8")
  return JSON.parse(raw) as SSoTRegistry
}

function getAllFlows(registry: SSoTRegistry): FlowDefinition[] {
  const list: FlowDefinition[] = []
  for (const domain of registry.domains) {
    for (const flow of domain.flows) {
      list.push({
        ...flow,
        domain_id: domain.id,
        domain_name: domain.name,
      })
    }
  }
  return list
}

describe("Unified 30-Flow Frontend Consistency & SSOT Compliance Suite", () => {
  const registry = loadRegistry()
  const allFlows = getAllFlows(registry)
  const repoRoot = path.resolve(__dirname, "../../../..")

  it("ensures the SSOT registry contains exactly 7 domains and 30 canonical flows", () => {
    expect(registry.domains.length).toBe(7)
    expect(allFlows.length).toBe(30)

    const ids = allFlows.map((f) => f.id).sort((a, b) => a - b)
    const expectedIds = Array.from({ length: 30 }, (_, i) => i + 1)
    expect(ids).toEqual(expectedIds)
  })

  it("verifies all 30 flows have non-empty contracts, valid UI surfaces, and backend endpoints", () => {
    for (const flow of allFlows) {
      expect(flow.name.trim()).toBeTruthy()
      expect(flow.title.trim()).toBeTruthy()
      expect(flow.ui_surface.startsWith("/")).toBe(true)
      expect(flow.backend_endpoint.trim()).toBeTruthy()
      expect(flow.invariant.trim()).toBeTruthy()
      expect(flow.test_ref.trim()).toBeTruthy()
      expect(flow.backend_test_ref?.trim()).toBeTruthy()
      expect(flow.frontend_test_ref?.trim()).toBeTruthy()
    }
  })

  it("verifies that each referenced test file actually exists in the repository", () => {
    for (const flow of allFlows) {
      const fullTestPath = path.resolve(repoRoot, flow.test_ref)
      const exists = fs.existsSync(fullTestPath)
      expect(
        exists,
        `Flow #${flow.id} (${flow.name}) references test_ref "${flow.test_ref}" which does not exist on disk.`
      ).toBe(true)

      if (flow.backend_test_ref) {
        const fullBackendPath = path.resolve(repoRoot, flow.backend_test_ref)
        expect(
          fs.existsSync(fullBackendPath),
          `Flow #${flow.id} (${flow.name}) references backend_test_ref "${flow.backend_test_ref}" which does not exist on disk.`
        ).toBe(true)
      }

      if (flow.frontend_test_ref) {
        const fullFrontendPath = path.resolve(repoRoot, flow.frontend_test_ref)
        expect(
          fs.existsSync(fullFrontendPath),
          `Flow #${flow.id} (${flow.name}) references frontend_test_ref "${flow.frontend_test_ref}" which does not exist on disk.`
        ).toBe(true)
      }
    }
  })

  it("verifies that all UI surfaces map to valid Next.js App Router route paths", () => {
    const validRoutePrefixes = [
      "/upload",
      "/portfolio",
      "/assets",
      "/statements",
      "/reconciliation",
      "/journal",
      "/reports",
      "/notifications",
      "/chat",
    ]

    for (const flow of allFlows) {
      const matchesKnownPrefix = validRoutePrefixes.some((prefix) =>
        flow.ui_surface.startsWith(prefix)
      )
      expect(
        matchesKnownPrefix,
        `Flow #${flow.id} UI surface "${flow.ui_surface}" does not match known app routes`
      ).toBe(true)
    }
  })

  describe("Domain-specific invariant validation", () => {
    it("Domain 1: Ingestion & Multimodal Extraction (Flows 1-5)", () => {
      const domain1 = registry.domains.find((d) => d.id === 1)
      expect(domain1).toBeDefined()
      expect(domain1?.flows.length).toBe(5)
      expect(domain1?.flows.map((f) => f.id)).toEqual([1, 2, 3, 4, 5])
    })

    it("Domain 2: Fact Review & Human-in-the-Loop (Flows 6-10)", () => {
      const domain2 = registry.domains.find((d) => d.id === 2)
      expect(domain2).toBeDefined()
      expect(domain2?.flows.length).toBe(5)
      expect(domain2?.flows.map((f) => f.id)).toEqual([6, 7, 8, 9, 10])

      // Flow 7: Inline repair
      const flow7 = domain2?.flows.find((f) => f.id === 7)
      expect(flow7?.component).toContain("LowConfidenceReviewModal")
    })

    it("Domain 3: Economic Intent & Categorization (Flows 11-14)", () => {
      const domain3 = registry.domains.find((d) => d.id === 3)
      expect(domain3).toBeDefined()
      expect(domain3?.flows.length).toBe(4)
      expect(domain3?.flows.map((f) => f.id)).toEqual([11, 12, 13, 14])

      // Flow 13: On-the-fly counter account
      const flow13 = domain3?.flows.find((f) => f.id === 13)
      expect(flow13?.component).toContain("UnmatchedBoard")
    })

    it("Domain 4: Cross-Source Reconciliation & Transfers (Flows 15-18)", () => {
      const domain4 = registry.domains.find((d) => d.id === 4)
      expect(domain4).toBeDefined()
      expect(domain4?.flows.length).toBe(4)
      expect(domain4?.flows.map((f) => f.id)).toEqual([15, 16, 17, 18])
    })

    it("Domain 5: Investments & Multi-Asset Valuation (Flows 19-22)", () => {
      const domain5 = registry.domains.find((d) => d.id === 5)
      expect(domain5).toBeDefined()
      expect(domain5?.flows.length).toBe(4)
      expect(domain5?.flows.map((f) => f.id)).toEqual([19, 20, 21, 22])
    })

    it("Domain 6: Financial Reporting & Accounting Equation Governance (Flows 23-26)", () => {
      const domain6 = registry.domains.find((d) => d.id === 6)
      expect(domain6).toBeDefined()
      expect(domain6?.flows.length).toBe(4)
      expect(domain6?.flows.map((f) => f.id)).toEqual([23, 24, 25, 26])

      // Flow 24: Equation diagnostic triage
      const flow24 = domain6?.flows.find((f) => f.id === 24)
      expect(flow24?.name).toContain("Accounting Equation Out-of-Balance")
    })

    it("Domain 7: Audit Traceability, Compliance & AI Insights (Flows 27-30)", () => {
      const domain7 = registry.domains.find((d) => d.id === 7)
      expect(domain7).toBeDefined()
      expect(domain7?.flows.length).toBe(4)
      expect(domain7?.flows.map((f) => f.id)).toEqual([27, 28, 29, 30])

      // Flow 28: ZIP export
      const flow28 = domain7?.flows.find((f) => f.id === 28)
      expect(flow28?.backend_endpoint).toBe("POST /reports/package/annual-archive")
    })
  })
})
