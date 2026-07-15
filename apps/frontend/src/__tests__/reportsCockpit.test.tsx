import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import ReportsPage from "@/app/(main)/reports/page"
import { apiFetch } from "@/lib/api"

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}))

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}))

const mockedApiFetch = vi.mocked(apiFetch)

const readiness = {
  package_id: "personal-financial-report-package",
  state: "blocked",
  label: "Blocked",
  action_href: "/review",
  blocking_count: 2,
  blockers: [
    {
      code: "pending_review",
      label: "Pending source review",
      severity: "blocking",
      count: 1,
      reason: "Statement review must be completed before reports are trusted.",
      action_href: "/review",
    },
    {
      code: "missing_source_coverage",
      label: "Missing source coverage",
      severity: "blocking",
      count: 1,
      reason: "Manual records need explicit source anchors.",
      action_href: "/journal",
    },
  ],
  source_summary: {
    statements: 3,
    posted_journal_entries: 4,
    manual_valuations: 1,
  },
  source_trust_summary: {
    source_classes: ["bank_statement", "manual_record"],
    deterministic_pr_source_classes: ["bank_statement", "manual_record"],
    post_merge_llm_ocr_source_classes: ["bank_statement"],
    manual_trusted_source_classes: ["manual_record"],
    gap_source_classes: ["manual_record"],
    blocker_codes: ["missing_source_coverage"],
  },
  generated_at: null,
  stale_since: null,
}

beforeEach(() => {
  mockedApiFetch.mockReset()
  mockedApiFetch.mockImplementation((path: string) => {
    if (path === "/api/income/annualized") {
      return Promise.resolve({ annualized_total: "120000.00", currency: "SGD" })
    }
    if (path === "/api/reconciliation/stats") {
      // match_rate is a 0–100 percentage from the backend, not a fraction.
      return Promise.resolve({ match_rate: 92, unmatched_transactions: 3 })
    }
    if (path.startsWith("/api/reports/package/readiness?")) {
      return Promise.resolve(readiness)
    }
    return Promise.resolve({})
  })
})

describe("Reports cockpit (EPIC-022 AC22.3)", () => {
  // AC-reporting.fe-ia-reports.2
  it("AC22.3.1 leads with exactly the four everyday report blocks and their live figures", async () => {
    render(<ReportsPage />)

    for (const title of ["Balance Sheet", "Income Statement", "Annualized Income", "Reconciliation coverage"]) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }

    // Annualized Income and Reconciliation coverage surface live numbers.
    await waitFor(() => expect(screen.getByText("92% matched")).toBeInTheDocument())
    expect(screen.getByText("3 unmatched")).toBeInTheDocument()
    expect(screen.getByText(/120,000/)).toBeInTheDocument()
  })

  // AC-reporting.fe-ia-reports.18
  it("AC22.9.1 keeps the reconciliation-coverage block in the reports context, not linked into Advanced", async () => {
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByText("Reconciliation coverage")).toBeInTheDocument())
    // The 4th cockpit block must not pull an everyday user into the Advanced
    // reconciliation surface.
    expect(screen.queryByRole("link", { name: /Reconciliation coverage/i })).toBeNull()
    for (const link of screen.queryAllByRole("link")) {
      expect(link.getAttribute("href")).not.toBe("/reconciliation")
    }
  })

  // AC-reporting.fe-ia-reports.19
  it("AC22.9.3 makes the Annualized Income card's destination match its label", async () => {
    render(<ReportsPage />)

    const card = screen.getByText("Annualized Income").closest("a")
    expect(card).not.toBeNull()
    // It opens the report package, and the caption says so — no silent mismatch.
    expect(card).toHaveAttribute("href", "/reports/package")
    expect(screen.getByText(/report package/i)).toBeInTheDocument()
  })

  // AC-reporting.fe-ia-reports.3
  it("AC22.3.2 keeps Cash Flow and the Personal Report Package behind the More control", async () => {
    render(<ReportsPage />)

    // Hidden from the front section until expanded.
    expect(screen.queryByText("Cash Flow Statement")).toBeNull()
    expect(screen.queryByText("Personal Report Package")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: /More reports/i }))

    await waitFor(() => expect(screen.getByText("Cash Flow Statement")).toBeInTheDocument())
    expect(screen.getByText("Personal Report Package")).toBeInTheDocument()
  })

  // AC-reporting.fe-viz-reports.32
  it("AC5.37.1 renders trust-first readiness before report cards", async () => {
    render(<ReportsPage />)

    const cockpit = await screen.findByRole("region", { name: "Report readiness cockpit" })
    await waitFor(() => expect(cockpit).toHaveTextContent("Blocked"))
    expect(cockpit).toHaveTextContent("2 blockers")
    expect(cockpit).toHaveTextContent("1 trust gap")
    expect(cockpit).toHaveTextContent("Manual records")
    expect(cockpit).toHaveTextContent("Pending source review")
    expect(screen.getByRole("link", { name: "Resolve report blockers" })).toHaveAttribute("href", "/review")

    const bodyText = document.body.textContent ?? ""
    expect(bodyText.indexOf("Report readiness")).toBeLessThan(bodyText.indexOf("Balance Sheet"))
  })

  it("AC5.37.2 preserves report navigation when readiness is unavailable", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/income/annualized") {
        return Promise.resolve({ annualized_total: "120000.00", currency: "SGD" })
      }
      if (path === "/api/reconciliation/stats") {
        return Promise.resolve({ match_rate: 92, unmatched_transactions: 3 })
      }
      if (path.startsWith("/api/reports/package/readiness?")) {
        return Promise.reject(new Error("readiness down"))
      }
      return Promise.resolve({})
    })

    render(<ReportsPage />)

    expect(await screen.findByText("Readiness unavailable")).toBeInTheDocument()
    expect(screen.getByText("Balance Sheet")).toBeInTheDocument()
    expect(screen.getByText("Income Statement")).toBeInTheDocument()
  })

  it("AC5.37.2 shows a checking state while readiness is still loading", () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/income/annualized") {
        return Promise.resolve({ annualized_total: "120000.00", currency: "SGD" })
      }
      if (path === "/api/reconciliation/stats") {
        return Promise.resolve({ match_rate: 92, unmatched_transactions: 3 })
      }
      if (path.startsWith("/api/reports/package/readiness?")) {
        return new Promise(() => undefined)
      }
      return Promise.resolve({})
    })

    render(<ReportsPage />)

    expect(screen.getByRole("region", { name: "Report readiness cockpit" })).toHaveTextContent("Checking report readiness")
    expect(screen.getByText("Balance Sheet")).toBeInTheDocument()
  })

  it("AC5.37.1 renders non-blocked readiness states without blocker copy", async () => {
    for (const [state, label, badgeClass] of [
      ["ready", "Ready", "badge-success"],
      ["generated", "Generated", "badge-success"],
      ["processing", "Processing", "badge-warning"],
      ["stale", "Stale", "badge-error"],
      ["draft", "Draft", "badge-muted"],
    ] as const) {
      mockedApiFetch.mockImplementation((path: string) => {
        if (path === "/api/income/annualized") {
          return Promise.resolve({ annualized_total: "120000.00", currency: "SGD" })
        }
        if (path === "/api/reconciliation/stats") {
          return Promise.resolve({ match_rate: 92, unmatched_transactions: 3 })
        }
        if (path.startsWith("/api/reports/package/readiness?")) {
          return Promise.resolve({
            ...readiness,
            state,
            label,
            action_href: "/reports/package",
            blocking_count: 0,
            blockers: [],
            source_trust_summary: {
              source_classes: ["unknown_source"],
              deterministic_pr_source_classes: [],
              post_merge_llm_ocr_source_classes: [],
              manual_trusted_source_classes: [],
              gap_source_classes: ["unknown_source"],
              blocker_codes: [],
            },
          })
        }
        return Promise.resolve({})
      })

      const view = render(<ReportsPage />)
      const cockpit = await screen.findByRole("region", { name: "Report readiness cockpit" })
      await waitFor(() =>
        expect(cockpit).toHaveTextContent(`Current package state is ${label.toLowerCase()}.`),
      )
      // sourceClassLabel's fallback is now the shared lib/statusLabels
      // humanizeIdentifier (title-cased, acronym-aware) — was a plain
      // replaceAll("_"," ") local to this page, #1868 S5.
      expect(cockpit).toHaveTextContent("Unknown Source")
      const statusBadge = Array.from(cockpit.querySelectorAll(".badge")).find(
        (badge) => badge.textContent === label,
      )
      expect(statusBadge).toHaveClass(badgeClass)
      expect(screen.getByRole("link", { name: "Open readiness path" })).toHaveAttribute("href", "/reports/package")
      view.unmount()
    }
  })

  it("AC5.37.1 renders an all-clear source gap state when readiness has no gaps", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path === "/api/income/annualized") {
        return Promise.resolve({ annualized_total: "120000.00", currency: "SGD" })
      }
      if (path === "/api/reconciliation/stats") {
        return Promise.resolve({ match_rate: 92, unmatched_transactions: 3 })
      }
      if (path.startsWith("/api/reports/package/readiness?")) {
        return Promise.resolve({
          ...readiness,
          state: "ready",
          label: "Ready",
          action_href: "/reports/package",
          blocking_count: 0,
          blockers: [],
          source_trust_summary: {
            source_classes: ["bank_statement"],
            deterministic_pr_source_classes: ["bank_statement"],
            post_merge_llm_ocr_source_classes: ["bank_statement"],
            manual_trusted_source_classes: [],
            gap_source_classes: [],
            blocker_codes: [],
          },
        })
      }
      return Promise.resolve({})
    })

    render(<ReportsPage />)

    const cockpit = await screen.findByRole("region", { name: "Report readiness cockpit" })
    await waitFor(() => expect(cockpit).toHaveTextContent("0 trust gaps"))
    expect(cockpit).toHaveTextContent("No source gaps reported.")
    expect(cockpit).toHaveTextContent("No blockers reported.")
  })
})
