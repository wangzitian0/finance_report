import "@testing-library/jest-dom/vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import GuidedEvidenceForm, {
  SOURCE_CLASS_CONFIGS,
  VALUATION_BASIS_OPTIONS,
  validateEvidenceForm,
} from "@/components/assets/GuidedEvidenceForm"
import GuidedEvidencePage from "@/app/(main)/portfolio/evidence/page"
import { apiFetch } from "@/lib/api"
import type {
  ManualValuationSnapshot,
  ManualValuationSnapshotListResponse,
} from "@/lib/types"

import { createInvalidationProbe } from "./fixtures/invalidationProbe"

const showToastMock = vi.fn()
const navigationState = vi.hoisted(() => ({
  sourceClass: null as string | null,
}))

vi.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams(
      navigationState.sourceClass ? { source_class: navigationState.sourceClass } : undefined,
    ),
}))

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const mockedApiFetch = vi.mocked(apiFetch)
const originalMatchMedia = window.matchMedia

const emptyList: ManualValuationSnapshotListResponse = { items: [], total: 0 }

const sampleSnapshot: ManualValuationSnapshot = {
  id: "snap-1",
  user_id: "u1",
  component_type: "rsu",
  liquidity_class: "restricted",
  as_of_date: "2026-05-18",
  value: "12500.00",
  currency: "USD",
  source: "Acme RSU grant (grant-2026.pdf p3)",
  valuation_basis: "employer_grant_document",
  notes: null,
  provenance: "manual",
  created_at: "2026-05-18T00:00:00Z",
  updated_at: "2026-05-18T00:00:00Z",
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  Wrapper.displayName = "GuidedEvidenceTestWrapper"
  return Wrapper
}

function mockListOnly(list: ManualValuationSnapshotListResponse = emptyList) {
  mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
    if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
      return Promise.resolve(list) as never
    }
    return Promise.reject(new Error(`Unexpected call ${path}`)) as never
  })
}

/** Fill the form with a valid, submittable evidence record. */
function fillValidForm() {
  fireEvent.change(screen.getByLabelText("Value / amount"), {
    target: { value: "12500" },
  })
  fireEvent.change(screen.getByLabelText("Source label"), {
    target: { value: "Acme RSU grant" },
  })
}

function mockMobileViewport() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    })),
  })
}

describe("GuidedEvidenceForm", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset()
    showToastMock.mockReset()
    navigationState.sourceClass = null
  })

  afterEach(() => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    })
  })

  // ── AC11.9.6 — required-field validation ────────────────────────────
  describe("AC11.9.6 required-field validation", () => {
    it("AC11.9.6 validateEvidenceForm flags missing basis and as-of date", () => {
      const { errors, blockers } = validateEvidenceForm({
        source_class: "esop_rsu_plan",
        value: "",
        currency: "SGD",
        as_of_date: "",
        valuation_basis: "",
        source_label: "",
        source_anchor: "",
        notes: "",
      })
      expect(errors.value).toBeTruthy()
      expect(errors.as_of_date).toBeTruthy()
      expect(errors.valuation_basis).toBeTruthy()
      expect(errors.source_label).toBeTruthy()
      expect(blockers).toEqual(
        expect.arrayContaining([
          "missing_value",
          "missing_as_of_date",
          "missing_valuation_basis",
          "missing_source_label",
        ]),
      )
    })

    it("AC11.9.6 non-numeric value is rejected as a blocker", () => {
      const { errors, blockers } = validateEvidenceForm({
        source_class: "property_statement",
        value: "abc",
        currency: "SGD",
        as_of_date: "2026-01-01",
        valuation_basis: "market_appraisal",
        source_label: "Condo appraisal",
        source_anchor: "",
        notes: "",
      })
      expect(errors.value).toBeTruthy()
      expect(blockers).toContain("missing_value")
    })

    it("AC11.9.6 non-positive and non-finite values are rejected as blockers", () => {
      const base = {
        source_class: "property_statement" as const,
        currency: "SGD",
        as_of_date: "2026-01-01",
        valuation_basis: "market_appraisal" as const,
        source_label: "Condo appraisal",
        source_anchor: "",
        notes: "",
      }
      // Zero and negative amounts are not valid positive evidence.
      for (const value of ["0", "0.00", "-5", "-12500.50"]) {
        const { errors, blockers } = validateEvidenceForm({ ...base, value })
        expect(errors.value).toBeTruthy()
        expect(blockers).toContain("missing_value")
      }
      // Non-decimal strings (including JS number literals like Infinity/NaN)
      // are rejected by the string-format check, never via Number()/parseFloat().
      for (const value of ["Infinity", "NaN", "1e3", "1,000", "  ", "12.34.56"]) {
        const { errors, blockers } = validateEvidenceForm({ ...base, value })
        expect(errors.value).toBeTruthy()
        expect(blockers).toContain("missing_value")
      }
    })

    it("AC11.9.6 well-formed positive decimal strings pass validation", () => {
      const base = {
        source_class: "property_statement" as const,
        currency: "SGD",
        as_of_date: "2026-01-01",
        valuation_basis: "market_appraisal" as const,
        source_label: "Condo appraisal",
        source_anchor: "",
        notes: "",
      }
      for (const value of ["1", "0.01", "12500", "12500.50", " 300000 "]) {
        const { blockers } = validateEvidenceForm({ ...base, value })
        expect(blockers).not.toContain("missing_value")
      }
    })

    it("AC11.9.6 a fully valid record has no blockers", () => {
      const { errors, blockers } = validateEvidenceForm({
        source_class: "liability_statement",
        value: "300000",
        currency: "SGD",
        as_of_date: "2026-01-01",
        valuation_basis: "bank_statement",
        source_label: "Mortgage statement",
        source_anchor: "",
        notes: "",
      })
      expect(errors).toEqual({})
      expect(blockers).toEqual([])
    })

    it("AC11.9.6 missing valuation basis blocks submit and never calls the API", async () => {
      mockListOnly()
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })

      // Clear the default basis to simulate a missing-basis readiness blocker.
      fillValidForm()
      fireEvent.change(screen.getByLabelText("Valuation basis"), {
        target: { value: "" },
      })
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      expect(
        await screen.findByText("Valuation basis is required"),
      ).toBeInTheDocument()
      expect(
        screen.getByTestId("evidence-readiness-blocker"),
      ).toBeInTheDocument()
      // Only the initial GET list call happened; no POST.
      expect(
        mockedApiFetch.mock.calls.filter(([, opts]) => opts?.method === "POST"),
      ).toHaveLength(0)
    })

    it("AC11.9.6 missing as-of date blocks submit", async () => {
      mockListOnly()
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })

      fillValidForm()
      fireEvent.change(screen.getByLabelText("As-of date"), {
        target: { value: "" },
      })
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      expect(
        await screen.findByText("As-of date is required"),
      ).toBeInTheDocument()
      expect(
        mockedApiFetch.mock.calls.filter(([, opts]) => opts?.method === "POST"),
      ).toHaveLength(0)
    })
  })

  // ── AC11.9.7 — typed manual-valuation persistence ───────────────────
  describe("AC11.9.7 typed persistence", () => {
    it("AC11.9.7 valid submit posts a Decimal-safe payload through the typed client", async () => {
      mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
        if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
          return Promise.resolve(emptyList) as never
        }
        if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
          return Promise.resolve(sampleSnapshot) as never
        }
        return Promise.reject(new Error(`Unexpected ${path}`)) as never
      })

      render(<GuidedEvidenceForm initialSourceClass="esop_rsu_plan" />, {
        wrapper: createWrapper(),
      })

      fillValidForm()
      fireEvent.change(screen.getByLabelText("Source anchor (optional)"), {
        target: { value: "grant-2026.pdf p3" },
      })
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      await waitFor(() =>
        expect(
          mockedApiFetch.mock.calls.some(([, opts]) => opts?.method === "POST"),
        ).toBe(true),
      )
      const postCall = mockedApiFetch.mock.calls.find(
        ([path, opts]) =>
          path === "/api/assets/valuation-snapshots" && opts?.method === "POST",
      )
      const body = JSON.parse((postCall?.[1]?.body as string) ?? "{}")
      expect(body).toMatchObject({
        component_type: "rsu",
        value: "12500",
        currency: "SGD",
        source: "Acme RSU grant (grant-2026.pdf p3)",
        valuation_basis: "employer_grant_document",
        notes: null,
      })
      expect(typeof body.as_of_date).toBe("string")
      // The monetary value is a string — never a float number.
      expect(typeof body.value).toBe("string")
      await waitFor(() =>
        expect(showToastMock).toHaveBeenCalledWith("Evidence saved", "success"),
      )
    })

    it("AC-testing.fe-async.2 guided-evidence create flow invalidates the matrix-declared query keys against a real QueryClient", async () => {
      // #1827 G-async-seam: only apiFetch is mocked; react-query runs for real.
      mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
        if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
          return Promise.resolve(emptyList) as never
        }
        if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
          return Promise.resolve(sampleSnapshot) as never
        }
        return Promise.reject(new Error(`Unexpected ${path}`)) as never
      })

      const probe = createInvalidationProbe("assets.guided-evidence-create")
      render(<GuidedEvidenceForm initialSourceClass="esop_rsu_plan" />, {
        wrapper: probe.wrapper,
      })

      fillValidForm()
      probe.expectNothingInvalidated()
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      await waitFor(() =>
        expect(
          mockedApiFetch.mock.calls.some(([, opts]) => opts?.method === "POST"),
        ).toBe(true),
      )
      await waitFor(() => probe.expectDeclaredInvalidated())
    })

    it("AC11.9.7 switching source class maps to the right component type and basis", async () => {
      mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
        if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
          return Promise.resolve(emptyList) as never
        }
        if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
          return Promise.resolve(sampleSnapshot) as never
        }
        return Promise.reject(new Error(`Unexpected ${path}`)) as never
      })

      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })

      fireEvent.change(screen.getByLabelText("Source class"), {
        target: { value: "liability_statement" },
      })
      fillValidForm()
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      await waitFor(() => {
        const postCall = mockedApiFetch.mock.calls.find(
          ([, opts]) => opts?.method === "POST",
        )
        const body = JSON.parse((postCall?.[1]?.body as string) ?? "{}")
        expect(body.component_type).toBe("other_liability")
        expect(body.valuation_basis).toBe("bank_statement")
      })
    })

    it("AC11.9.7 surfaces API errors via toast and does not crash", async () => {
      mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
        if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
          return Promise.resolve(emptyList) as never
        }
        return Promise.reject(new Error("save failed")) as never
      })

      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })
      fillValidForm()
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      await waitFor(() =>
        expect(showToastMock).toHaveBeenCalledWith(
          "Failed to save evidence: save failed",
          "error",
        ),
      )
    })

    it("AC11.9.7 omits the anchor suffix when no anchor is provided", async () => {
      mockedApiFetch.mockImplementation((path: string, options?: RequestInit) => {
        if (path.startsWith("/api/assets/valuation-snapshots") && !options) {
          return Promise.resolve(emptyList) as never
        }
        if (path === "/api/assets/valuation-snapshots" && options?.method === "POST") {
          return Promise.resolve(sampleSnapshot) as never
        }
        return Promise.reject(new Error(`Unexpected ${path}`)) as never
      })

      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })
      fireEvent.change(screen.getByLabelText("Currency"), {
        target: { value: "usd" },
      })
      fireEvent.change(screen.getByLabelText("Notes (optional)"), {
        target: { value: "Quarterly review" },
      })
      fillValidForm()
      fireEvent.click(screen.getByRole("button", { name: "Save evidence" }))

      await waitFor(() => {
        const postCall = mockedApiFetch.mock.calls.find(
          ([, opts]) => opts?.method === "POST",
        )
        const body = JSON.parse((postCall?.[1]?.body as string) ?? "{}")
        expect(body.source).toBe("Acme RSU grant")
        expect(body.currency).toBe("USD")
        expect(body.notes).toBe("Quarterly review")
      })
    })
  })

  // ── AC11.9.8 — manual-trusted disclosure label ──────────────────────
  describe("AC11.9.8 manual-trusted disclosure", () => {
    it("AC11.9.8 form shows a manual-trusted badge", () => {
      mockListOnly()
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })
      expect(screen.getByTestId("manual-trusted-badge")).toHaveTextContent(
        "Manual-trusted",
      )
    })

    it("AC11.9.8 recent evidence rows are labelled manual-trusted with basis", async () => {
      mockListOnly({ items: [sampleSnapshot], total: 1 })
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })

      const panel = await screen.findByTestId("recent-evidence-panel")
      await within(panel).findByText("Acme RSU grant (grant-2026.pdf p3)")
      expect(
        within(panel).getAllByText("Manual-trusted").length,
      ).toBeGreaterThan(0)
      expect(
        within(panel).getByText(/employer grant document/i),
      ).toBeInTheDocument()
    })

    it("AC11.9.8 renders an empty state and tolerates a missing basis", async () => {
      mockListOnly({
        items: [{ ...sampleSnapshot, id: "s2", valuation_basis: null }],
        total: 1,
      })
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })
      const panel = await screen.findByTestId("recent-evidence-panel")
      await within(panel).findByText("Acme RSU grant (grant-2026.pdf p3)")
      expect(within(panel).queryByText(/·/)).not.toBeInTheDocument()
    })

    it("AC11.9.8 shows empty copy when there is no evidence", async () => {
      mockListOnly()
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })
      expect(
        await screen.findByText("No evidence recorded yet."),
      ).toBeInTheDocument()
    })
  })

  // ── AC11.9.9 — mobile layout ────────────────────────────────────────
  describe("AC11.9.9 mobile layout", () => {
    it("AC11.9.9 renders accessible single-column form on a mobile viewport", async () => {
      mockMobileViewport()
      mockListOnly()
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })

      const form = screen.getByRole("form", { name: "Guided evidence form" })
      expect(form).toBeInTheDocument()
      expect(screen.getByLabelText("Value / amount")).toBeVisible()
      expect(screen.getByLabelText("As-of date")).toBeVisible()
      expect(screen.getByTestId("recent-evidence-panel")).toBeInTheDocument()
    })

    it("AC11.9.9 degrades gracefully when matchMedia is unavailable", async () => {
      Object.defineProperty(window, "matchMedia", {
        configurable: true,
        writable: true,
        value: undefined,
      })
      mockListOnly()
      render(<GuidedEvidenceForm />, { wrapper: createWrapper() })
      expect(
        screen.getByRole("form", { name: "Guided evidence form" }),
      ).toBeInTheDocument()
    })
  })

  // ── Page wrapper + exported config integrity ────────────────────────
  it("renders the guided evidence page with the form", () => {
    mockListOnly()
    render(<GuidedEvidencePage />, { wrapper: createWrapper() })
    expect(
      screen.getByRole("heading", { name: "Guided evidence intake", level: 1 }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("form", { name: "Guided evidence form" }),
    ).toBeInTheDocument()
  })

  it("AC19.15.1 opens guided evidence at the requested source class", () => {
    navigationState.sourceClass = "liability_statement"
    mockListOnly()
    render(<GuidedEvidencePage />, { wrapper: createWrapper() })

    expect(screen.getByLabelText("Source class")).toHaveValue("liability_statement")
  })

  it("covers all three guided source classes and seven valuation bases", () => {
    expect(SOURCE_CLASS_CONFIGS.map((c) => c.value)).toEqual([
      "esop_rsu_plan",
      "property_statement",
      "liability_statement",
    ])
    expect(VALUATION_BASIS_OPTIONS).toHaveLength(7)
  })

  it("falls back to the first source class for an unknown initial value", () => {
    mockListOnly()
    render(
      // @ts-expect-error deliberately passing an invalid source class
      <GuidedEvidenceForm initialSourceClass="unknown_class" />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByLabelText("Source class")).toHaveValue("esop_rsu_plan")
  })
})
