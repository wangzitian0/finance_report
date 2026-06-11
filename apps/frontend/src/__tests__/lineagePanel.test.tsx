import { render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { LineagePanel } from "@/components/reports/LineagePanel"
import { apiFetch } from "@/lib/api"
import type { LineageAnchor } from "@/lib/lineage"

vi.mock("@/components/ui/Sheet", () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) =>
    isOpen ? (
      <div role="dialog" aria-label={title}>
        {children}
      </div>
    ) : null,
}))

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }))

const mockedApiFetch = vi.mocked(apiFetch)

const JOURNAL_ANCHOR: LineageAnchor = {
  entity_type: "journal_line",
  entity_id: "11111111-1111-4111-8111-111111111111",
  node_kind: "ledger_line",
}

beforeEach(() => {
  mockedApiFetch.mockReset()
})

describe("LineagePanel (EPIC-022 AC22.3.4/AC22.3.5)", () => {
  it("AC22.3.4 renders the evidence chain from ledger line to source document", async () => {
    mockedApiFetch.mockResolvedValue({
      anchor: null,
      max_depth: 6,
      blockers: [],
      edges: [],
      nodes: [
        { id: "n1", node_kind: "ledger_line", entity_type: "journal_line", entity_id: "j1", properties: {} },
        { id: "n2", node_kind: "extracted_record", entity_type: "bank_statement_transaction", entity_id: "s1", properties: {} },
        { id: "n3", node_kind: "atomic_fact", entity_type: "atomic_transaction", entity_id: "a1", properties: {} },
        { id: "n4", node_kind: "source_document", entity_type: "uploaded_document", entity_id: "d1", properties: {} },
      ],
    })

    render(<LineagePanel anchor={JOURNAL_ANCHOR} title="Salary deposit" onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText("ledger line")).toBeInTheDocument())
    expect(screen.getByText("extracted record")).toBeInTheDocument()
    expect(screen.getByText("atomic fact")).toBeInTheDocument()
    expect(screen.getByText("source document")).toBeInTheDocument()
    // The anchored call targets the evidence lineage API for that journal line.
    expect(mockedApiFetch).toHaveBeenCalledWith(expect.stringContaining("/api/evidence/lineage?entity_type=journal_line"))
  })

  it("AC22.3.5 shows a graceful empty/blocker state when nothing is linked", async () => {
    mockedApiFetch.mockResolvedValue({
      anchor: null,
      max_depth: 6,
      blockers: [{ code: "graph_node_missing", message: "No graph node for this anchor" }],
      edges: [],
      nodes: [],
    })

    render(<LineagePanel anchor={JOURNAL_ANCHOR} title="Unlinked amount" onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText("No graph node for this anchor")).toBeInTheDocument())
    expect(screen.getByText("No source records are linked to this amount yet.")).toBeInTheDocument()
  })

  it("AC22.3.5 surfaces a load error without crashing", async () => {
    mockedApiFetch.mockRejectedValue(new Error("lineage boom"))

    render(<LineagePanel anchor={JOURNAL_ANCHOR} title="Erroring amount" onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText("lineage boom")).toBeInTheDocument())
  })

  it("AC22.3.5 stays closed and issues no request when there is no anchor", () => {
    render(<LineagePanel anchor={null} title="None" onClose={() => {}} />)

    expect(screen.queryByRole("dialog")).toBeNull()
    expect(mockedApiFetch).not.toHaveBeenCalled()
  })
})
